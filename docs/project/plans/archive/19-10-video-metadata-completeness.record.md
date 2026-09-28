# Build record - 10-video-metadata-completeness

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/19-10-video-metadata-completeness.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Video page metadata completeness: show tags/category and refresh mutable fields\n\nStatus: enhancement, needs-triage\nOrigin: task 3, [M2][F1]\n\n## Problem\n\nThe video page does not show all useful metadata (especially tags and category), and the per-request metadata refresh focuses on dynamic stats (views/likes) while other fields may also change.\n\n## Proposed solution\n\nRender tags and category on the video page, and extend the per-request refresh to update mutable video fields from the source instance.\n\n- **UI:** visible blocks for `category` (or its label) and `tags` (chips, with an empty state); compact and consistent with the existing metadata area.\n- **Refresh on video request:** keep the `views`/`likes` refresh; also refresh `title`, `description`, `tags`, `category`, and optionally `language`, `nsfw`, `duration`, `thumbnail_url`; one write path with clear mapping rules.\n- **Data model:** tags/category stored in the schema `/api/video` reads; a numeric source category maps to a display label consistently.\n- **Robustness \u2014 keep the current fallback** in `engine/server/api/handlers/video.py`: instance fetch with `timeout=8` catching `HTTPError`/`URLError`/`TimeoutError`; on failure the response falls back field by field to the DB; the DB update and `instances.last_error` reset run only on a successful refresh. Document it in tests.\n\n## Validation (from the original task)\n\n- Manual: tags/category render on the video page.\n- Integration: a source metadata change is reflected after the next `/api/video` request.\n- DB persistence on a test DB mirroring the production schema: success and instance-fail fixtures; assert saved `title/description/views/likes/dislikes/tags_json/category/nsfw/last_checked_at`; assert no overwrite on the failed path.\n- Regression: stats refresh does not wipe tags/category on partial responses.\n\n## Comments",
  "request_source": "read from docs/project/issues/10-video-metadata-completeness.md",
  "slug": "10-video-metadata-completeness",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done",
    "10": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "language column in both producers",
      "checkpoint": "Two seams, each following an existing harness. (a) New `tests/active/test_video_handler.py::test_migration_adds_language_column`: it loads `sync-whitelist.py` and `whitelist_migrations.py` with `spec_from_file_location` (precedent: `test_repair_video_channel_names.py`) and builds the pre-change `videos` table inline in a tmp_path DB, error columns included and `language` left out. It runs `ensure_whitelist_schema` + `ensure_content_schema`, inserts two videos, and calls `migrate_whitelist_schema(conn, \"instances\")`. It then asserts that `language` is among the `PRAGMA table_info(videos)` names, that the `(video_id, title, tags_json, category)` rows are unchanged with `language` NULL, that 3 `videos_fts_%` triggers exist, and that a second run leaves `table_info` identical. (b) `tests/active/test_videos_worker.py`, which runs the committed `dist/videos-worker.js` under node against local PeerTube stand-ins, keeping its stale-dist and missing-tool guards. The existing case gains `language` on the alpha videos and asserts `{a-1: \"en\", a-2: None, b-1: None}`. The new `test_crawl_adds_language_to_existing_db` seeds crawl.db from `schema.sql` with the `language` line removed (asserting the text really differs) and asserts that the column exists after the crawl and that a-1 has `language == \"de\"`.",
      "intent": "Every videos table the build touches has a nullable `language` column: `whitelist_migrations.migrate_whitelist_schema` adds it to an existing whitelist DB without losing rows or FTS triggers, and the crawler (`schema.sql`, `db.ts`, `videos-worker.ts`) stores each video's PeerTube language code in crawl.db, adding the column to a crawl.db that predates it.",
      "clauses": [
        {
          "id": "C1",
          "text": "`migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing."
        },
        {
          "id": "C2",
          "text": "A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed."
        }
      ],
      "files": [
        "engine/crawler/schema.sql (EDITED)",
        "engine/crawler/src/db.ts (EDITED)",
        "engine/crawler/src/videos-worker.ts (EDITED)",
        "engine/crawler/dist/db.js (EDITED)",
        "engine/crawler/dist/videos-worker.js (EDITED)",
        "engine/server/db/jobs/whitelist_migrations.py (EDITED)",
        "engine/server/db/jobs/sync-whitelist.py (EDITED)",
        "tests/active/test_video_handler.py (NEW)",
        "tests/active/test_videos_worker.py (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/crawler/schema.sql\n- Added `language TEXT,` after `category TEXT,` in `videos`. No index, because the first `db.exec(schemaSql)` runs against old tables.\n\n### engine/crawler/src/db.ts\n- New `migrateVideosLanguage(db)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`.\n- `applyBaseSchema` calls it after `migrateVideos` and before the second `db.exec(schemaSql)`, so a table the old rebuild just produced also gets the column.\n- The `migrateVideos` rebuild carries `language`: new `hasLanguage`/`languageExpr`, `language TEXT` in `videos_new`, and `language` / `${languageExpr}` after `category` in the INSERT and SELECT lists.\n- `VideoUpsertRow` has a new field `language: string | null`.\n- The upsert has `language` in its INSERT list, 26 `?` before `NULL, NULL, 0`, and `language = excluded.language` in ON CONFLICT. `upsertVideos` passes `row.language` right after `row.category`.\n- As the plan says, a re-crawl whose payload has `{id: null}` overwrites crawl.db's `language` with NULL. That matches how `category` is handled.\n\n### engine/crawler/src/videos-worker.ts\n- New `PeerTubeLanguage` interface `{ id?: string | null; label?: string }`, and `PeerTubeVideo.language?: PeerTubeLanguage | string`.\n- New `extractLanguage`: takes an object's `id` or a plain string, trimmed; a null id, a number, `\"\"` or whitespace gives `null`.\n- `toVideoRow` sets `language: extractLanguage(video.language)`.\n\n### engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js\n- Hand-edited to match the source changes above, in tsc's output style: 4-space indent, bodies of one-line `if`s on their own line, JSDoc kept. I couldn't run `npm run build`.\n- A throwaway probe (below) ran the edited dist under node against a local PeerTube stand-in. It exited with code 0, and the pre-change crawl.db gained `language` as its last column.\n- Rows it produced: `a-0` \"Old\" not revisited, `language` NULL; `a-1` title updated to \"A one\" through the conflict path, `language` \"de\"; `{id: null}` gave NULL; a video with no `language` gave NULL.\n- Both dist files were written after their sources, so the checkpoint's mtime staleness check passes while they are uncommitted.\n- Recommended before commit, but not needed for the checkpoint: run `cd engine/crawler && npm install && npm run build` and review the dist diff, so the committed dist is real tsc output.\n\n### engine/server/db/jobs/whitelist_migrations.py\n- New `migrate_videos_language(conn)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`. Rows, `videos_fts` and its triggers are untouched, and a second run does nothing.\n- `migrate_whitelist_schema` calls it last, after `migrate_videos_schema`.\n- The `migrate_videos_schema` rebuild carries `language` conditionally (`has_language`/`language_expr`; column after `category` in `videos_new`, the INSERT list and the SELECT list), so no rebuild can drop it.\n\n### engine/server/db/jobs/sync-whitelist.py\n- `ensure_content_schema`'s `CREATE TABLE videos` has a new `language TEXT,` after `category TEXT,`.\n- Nothing else changes: `VIDEO_COLUMNS` is parsed from `schema.sql`, so the exact check, the superset check and the copy column list all pick `language` up automatically.\n\n### tests/tmp/probe_10_dist_language.py\n- The throwaway probe described above. I have no delete tool, so I overwrote it with an empty file; it collects no tests. Please delete it.\n\n### Not touched\n- `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are in the phase's files list, but they are test files that the checkpoint promotion carries. This step is production code only, so I left them alone.",
      "beyond": "tests/tmp/probe_10_dist_language.py - a throwaway probe used to watch the hand-edited dist run under node. Emptied, because I have no tool that deletes files; the operator should remove it."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "default display labels in /api/video",
      "checkpoint": "`tests/active/test_video_handler.py::test_response_labels`, parametrised on `(\"15\",\"en\")`, `(\"99\",\"zh-Hans\")` and `(\"Music\",\"xx\")`. The seam is `handlers.video.handle_video_request(None, server, params)`, imported with `engine/server` and `engine/server/api` on `sys.path` (precedent: `test_internal_events.py`). `server` is a `SimpleNamespace(db, db_lock, video_error_threshold, popularity_like_weight)` over a tmp_path DB built from `sync-whitelist.py`'s `ensure_whitelist_schema` + `ensure_content_schema` and seeded with one instance, one channel and one video. `video.respond_json` is monkeypatched to capture `(status, body)`, and `video.fetch_instance_json` is stubbed to return None, so the answer comes from the DB. The test UPDATEs the seeded row's category and language, then asserts that the response's `category` and `language` equal \"Science & Technology\"/\"English\", \"99\"/\"Simplified Chinese\" and \"Music\"/\"xx\", and that the stored values are still the raw id and code.",
      "intent": "The `/api/video` response built by `handle_video_request` carries `category` and `language` as PeerTube default display labels from the new `engine/server/data/peertube_labels.py`, while the stored values stay ids and codes.",
      "clauses": [
        {
          "id": "C1",
          "text": "A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored."
        },
        {
          "id": "C2",
          "text": "A stored language code is answered with its PeerTube default label, and an unknown code is answered raw."
        }
      ],
      "files": [
        "engine/server/data/peertube_labels.py (NEW)",
        "engine/server/api/handlers/video.py (EDITED)",
        "tests/active/test_video_handler.py (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/server/data/peertube_labels.py (NEW)\n- A stdlib-only module that follows the `data/*.py` style: a module docstring, `from __future__ import annotations`, and a docstring on each function. It does no work at import beyond the literals.\n- `CATEGORY_LABELS` maps `\"1\"`\u2013`\"18\"` to exactly the labels listed in R4. A `rat-tail:` comment names the ceiling (stock PeerTube lists only; plugin-added or renamed entries show raw) and the upgrade path (cache each instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`).\n- `LANGUAGE_LABELS` is the stock instance's `GET /api/v1/videos/languages` body that the operator pasted during this step, copied verbatim onto one line. This is the Step 6 manual replacement, and the plan's from-memory draft was never committed. The live list differs from the draft in places: `es` is \"Spanish (Spain)\", `pt` is \"Portuguese (Brazilian)\", `km` is \"Khmer\", and it adds `es-419`, `ca-valencia`, `zxx`, `gcf`, `gcr`, `rcf`, `gsw`, `sh` and `fse`. `en` \u2192 \"English\" and `zh-Hans` \u2192 \"Simplified Chinese\" are both there.\n- `category_label(value)`: returns `\"\"` when the value is empty or not a string. A string that is all ASCII digits (`isascii()` plus `isdigit()`) goes through the map, and an unknown id comes back unchanged. Any other value is returned as it is.\n- `language_label(value)`: returns `\"\"` when the value is empty or not a string. Otherwise it does a case-sensitive lookup, and an unknown code comes back raw.\n\n### engine/server/api/handlers/video.py (EDITED)\n- Imports `category_label` and `language_label` from `data.peertube_labels`.\n- `fetch_video_row` now also selects `v.language`.\n- The response dict gains two keys, and all existing keys are unchanged:\n  - `\"category\"`: `category_label(category)`. `category` is the existing merged value (source first, then the DB).\n  - `\"language\"`: `language_label(row.get(\"language\"))`.\n- Labels are applied only when building the response. The UPDATE still writes the raw merged `category`, and `language` is not written at all yet, so the stored id and code stay as they were. That is what `test_refresh_stores_raw_codes` checks.\n- Not in this phase: language merging from the source, the success-only write guard and the other R5 keys. They belong to Phase 3.\n\n### tests/active/test_video_handler.py\n- Not touched. It is on the phase's files list, but it holds the checkpoint that checkpoint promotion carries. This step is production code only."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "refresh only on success, one merge",
      "checkpoint": "This uses the same `handle_video_request` harness as phase 2, in `tests/active/test_video_handler.py`. Failure seam: `test_fetch_failure_leaves_db_untouched` is parametrised as `stub-none` (`fetch_instance_json` returns None), `urlopen-urlerror`, `not-json`, `bad-utf8` and `json-list`. The last four replace `video.urlopen` with a raiser or a `_FakeResponse`, so the real parse guard in `fetch_instance_json` runs. The test asserts that the `SELECT *` snapshots of the videos row, all channels rows and `instances.last_error*` are equal before and after, and that the status-200 response carries the DB values (title, description, views, tags [\"old\"], category \"Music\", language \"French\", nsfw False, duration 10, thumbnailUrl, channelName). Success seam: a path-keyed `fetch_instance_json` stub drives four tests. `test_success_refreshes_row_and_response` checks that every refreshed column is stored, that `last_checked_at` moved forward, that `instances.last_error*` is NULL, and that the response's new keys equal the stored values while the 18 original keys remain. `test_partial_payload_keeps_tags_and_category` checks that views update while the stored tags_json, category and language stay. `test_empty_tag_list_propagates` checks that \"[]\" is stored and `[]` is answered. `test_second_request_reflects_source_change` checks that the second response and the DB carry the renamed title and the new tags.",
      "intent": "`handle_video_request` in `engine/server/api/handlers/video.py` writes to the DB only when the video detail fetch returns a JSON object, and on success it stores and answers one merged source-over-DB value set, including tags, category, language, nsfw, duration and thumbnail.",
      "clauses": [
        {
          "id": "C1",
          "text": "A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values."
        },
        {
          "id": "C2",
          "text": "A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values."
        }
      ],
      "files": [
        "engine/server/api/handlers/video.py (EDITED)",
        "tests/active/test_video_handler.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/handlers/video.py`\n- **`fetch_video_row`** now also selects `v.duration` and `v.thumbnail_url`, so a failed fetch can still answer them from the DB. `v.language` was already selected in phase 2.\n- **`fetch_instance_json`** returns a `dict` or `None`. It still calls `urlopen(req, timeout=8)`, still catches `HTTPError`/`URLError`/`TimeoutError`, and a non-200 status still returns `None`. Two more cases return `None` and log at info:\n  - a `ValueError` (this covers both `UnicodeDecodeError` and `JSONDecodeError`);\n  - a parsed body that is not a `dict`.\n  The `# pragma: no cover` on the except line is gone.\n- **New helpers:**\n  - `pick_present(value, fallback)`: returns the source value unless it is None, otherwise the DB value.\n  - `id_text`: turns an int (never a bool) or a non-empty trimmed string into text.\n  - `tags_from_json`: parses the stored `tags_json` into its string tags. Null, empty, invalid or non-list values give `[]`.\n  - `extract_language`: returns an object's `id`, or a plain non-empty string, through `pick_text`. A null id gives `None`.\n- **Changed helpers:**\n  - `to_tags_json` returns `\"[]\"` for an empty list, and `None` only when the value is not a list. It writes raw UTF-8 (`ensure_ascii=False`) to match the crawler, as the settled draft decided.\n  - `extract_category` falls back to the id as text when there is no label. Plain values go through `id_text`, so `\"\"` or whitespace keeps the DB value.\n- **`fetch_instance_video_dynamic`** returns `None` exactly when the detail fetch gives no dict. This is the single success signal. `account` and `channel` are guarded with `isinstance(dict)`. The function now also returns:\n  - `language`, from `extract_language`;\n  - `duration`, from `pick_number`;\n  - `thumbnail_url`, from `resolve_asset_url(thumbnailUrl or thumbnailPath)`, with `\"\"` mapped to `None` so a missing thumbnail never blanks the stored one.\n  The channel-detail fallback is unchanged, so if that second fetch fails, the stored follower count is kept.\n- **`handle_video_request`**\n  - If there is no host, or the fetch fails, `dynamic` is `None` and `source = {}`.\n  - One merged value set (source value where present, else the DB value) now covers title, description, stats, channel, tags_json, category, language, nsfw, duration and thumbnail_url. The same set feeds the response and the UPDATE.\n  - The response keeps all 18 original keys. `accountAvatarUrl` now reads from `source`. Four keys are added: `tags` (a list), `nsfw` (a bool or null), `duration` and `thumbnailUrl`. `language` now labels the merged code rather than the DB row's code.\n  - The write guard is now `dynamic is not None`, which checks identity rather than truthiness. On failure no `videos`, `channels` or `instances` statement runs. A `{}` body still counts as a success.\n  - The `videos` UPDATE also sets `language`, `duration` and `thumbnail_url`. The `channels` UPDATE, the `instances.last_error*` reset, the transaction and the `OperationalError` catch are unchanged.\n\n### `tests/active/test_video_handler.py`\nNot touched. The phase lists it as EDITED, but it does not exist in this worktree. This phase's checkpoint lives in `tests/tmp/test_10_video_metadata_completeness_phase3.py`, and I did not edit that file either. Presumably it is moved into `tests/active` at harvest.\n\nNot run: I did not execute the checkpoint myself. I checked it by reading each test's cases against the code. The phase 2 checkpoint (`test_refresh_stores_raw_codes`, where an id-only category is now stored as `\"15\"` rather than keeping the DB value) should also stay green under the new rules, but that too is from reading, not from a run."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "taxonomy block on the video page",
      "checkpoint": "New `tests/active/test_frontend_video_taxonomy.py`, following the esbuild-bundle + node-runner precedent of `test_frontend_videos.py` / `test_frontend_blocks.py`. It bundles `client/frontend/src/pages/video-page/index.ts` with `client/frontend/node_modules/.bin/esbuild` (`--platform=node`, with a CSS loader or empty stub for `video.css`). A runner stubs the platform node lacks: a `document` whose `getElementById` returns a recorded stub element per id, with `createElement` and `replaceChildren`; `window.location.search` carrying `id` and `host`; `localStorage`/`sessionStorage`; and `fetch`, which returns a fixture body for `/api/video` and empty payloads elsewhere. After `loadVideo` settles, the runner reports the `textContent` and `hidden` of `video-category`, `video-category-value`, `video-language`, `video-language-value` and the `video-tags` children. Case 1 uses a body with category \"Science & Technology\", language \"English\" and tags [\"alpha\",\"beta\"], and asserts the two values are visible and there is one `tag-chip` per tag with the tag as its text. Case 2 uses a body with category \"\", language \"\" and tags [], and asserts the category and language items are hidden and the only tag child reads \"No tags\".",
      "intent": "The video page (`video-page.html`, `pages/video-page/index.ts`, `video.css`) has a `video-taxonomy` block that shows the category, language and tags from `/api/video` as text only.",
      "clauses": [
        {
          "id": "C1",
          "text": "For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag."
        },
        {
          "id": "C2",
          "text": "For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads \"No tags\"."
        }
      ],
      "files": [
        "client/frontend/video-page.html (EDITED)",
        "client/frontend/src/pages/video-page/index.ts (EDITED)",
        "client/frontend/src/video.css (EDITED)",
        "client/frontend/dist (EDITED",
        "rebuilt; orphaned hashed video assets deleted)",
        "tests/active/test_frontend_video_taxonomy.py (NEW)"
      ],
      "done": true,
      "outcome": "### client/frontend/src/pages/video-page/index.ts\n- Added lookups for the new elements: `video-category`, `video-category-value`, `video-language`, `video-language-value` and `video-tags`.\n- `VideoMetadata` has three new fields: `category?: string`, `language?: string` and `tags?: string[]`.\n- `fetchVideoMetadataFromServer` reads `category` and `language` from the `/api/video` body, and uses `\"\"` when either is missing. It reads `tags` only if it is an array, and keeps only the string entries; otherwise it uses `[]`.\n- `loadVideo` fills in the block using a new helper, `renderTaxonomyItem(itemEl, valueEl, value)`. It hides the item when the value is empty and sets the value as text. The tag list gets one `<span class=\"tag-chip\">` per tag through `replaceChildren`, with each chip's text set as text. With no tags, the list's text is set to \"No tags\". Nothing goes through `innerHTML`, because tags come from remote instances.\n- Not done: the PeerTube instance fallback (`fetchVideoMetadataFromInstance`) does not map `category`, `language` or `tags`. Phase 4 is limited to `/api/video`. When the page falls back to the instance, both items stay hidden and the tag list reads \"No tags\".\n\n### client/frontend/video-page.html\n- Added `<dl id=\"video-taxonomy\" class=\"video-taxonomy\">` between `video-meta-row` and `video-description`. It has three `taxonomy-item` rows:\n  - Category: `#video-category` holding `dd#video-category-value`\n  - Language: `#video-language` holding `dd#video-language-value`\n  - Tags: `dd#video-tags.tag-list`\n- The category and language rows start `hidden`, so they don't show as empty labels before the metadata arrives.\n\n### client/frontend/src/video.css\n- New rules for `.video-taxonomy`, `.taxonomy-item` and its `dt`/`dd`, `.tag-list` and `.tag-chip`. The chips are pill-shaped like the existing `.instance-meta` chips.\n- Added `.taxonomy-item[hidden] { display: none; }`. Without it, the flex display on `.taxonomy-item` would override the `hidden` attribute.\n\n### client/frontend/dist\n- **Not rebuilt.** I have no shell, so I couldn't run `npm run build` or delete the old hashed `video-*.js` / `video-*.css` files it replaces. The checkpoint builds its own bundle from `src` with esbuild and doesn't read `dist`, so it isn't affected. As agreed at Step 6, the operator still needs to run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before the merge.\n\n### tests/active/test_frontend_video_taxonomy.py\n- Not created by me. The checkpoint is `tests/tmp/test_10_video_metadata_completeness_phase4.py`, and I assume the workflow moves it to this path. I left it untouched.\n\n### Observation\n- A probe (`tests/tmp/probe_10_phase4_impl.py`) built the edited `index.ts` with the checkpoint's own esbuild command and ran it under the checkpoint's runner. Results:\n  - **Body 1:** category and language showing with \"Science & Technology\" and \"English\"; tags `alpha` and `beta` as `tag-chip`s.\n  - **Empty body:** both items hidden; the only child of the tag list is \"No tags\".\n  - **Music body:** only the language item hidden; one `solo` chip.\n- In all three cases the control fields matched: `/api/video` was requested and the title was rendered.",
      "beyond": "tests/tmp/probe_10_phase4_impl.py - my throwaway probe (see changes). I have no tool that deletes files, so it's still there and needs removing by hand."
    }
  ],
  "digests": {
    "tests/tmp/test_10_video_metadata_completeness_phase1.py": "039f465c9a035f3e8e37fda0ddbe0531789c232f7f11453f6555f8e87185f86f",
    "tests/tmp/test_10_video_metadata_completeness_phase2.py": "56c7972729ca2c04843c70719e7e3ee48d55e6471c4c75802316aa5f0f5befe8",
    "tests/tmp/test_10_video_metadata_completeness_phase3.py": "9db0a391a131d0306da94278881500b20b12b6d333b6a7f9b0cef29b22c4b27b",
    "tests/tmp/test_10_video_metadata_completeness_phase4.py": "1f6351146dd25c2667812d28d727cd6e7490801a5cb36c701ef8cb1cf66c83a9"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/10",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260927T195148-875e-dev-flow"
  ],
  "plan": "docs/project/plans/19-10-video-metadata-completeness.md",
  "record": "docs/project/plans/19-10-video-metadata-completeness.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nThe video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) must show what the source PeerTube instance currently says about a video, including its tags, category and language. Every `/api/video` request (`engine/server/api/handlers/video.py`, `handle_video_request`) must bring the server DB copy of the video's mutable fields up to date, and that copy also feeds search FTS (`videos_fts` triggers) and embeddings (`build-video-embeddings.py` reads `tags_json`/`category`). A failed or unreachable instance must never change stored data.\n\n### Baseline suite state\n\nPre-build suite exited 0 (variant: false). Resolved paths: active tests `tests/active`, working tests `tests/tmp`, plans `docs/project/plans`, archive `tests/archive`, delete_me `delete_me`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser/.worktrees/10`.\n\n### Current state found in the tree (context for later steps)\n\n- `fetch_instance_video_dynamic` already fetches `/api/v1/videos/{id}` plus `/api/v1/video-channels/{slug}`, normalises title/description/views/likes/dislikes/tags_json/category/nsfw, and the handler already UPDATEs `videos` (title, description, channel_name, views, likes, dislikes, popularity, tags_json, category, nsfw, last_checked_at), `channels`, and resets `instances.last_error/last_error_at/last_error_source`.\n- Defect: `fetch_instance_video_dynamic` always returns a non-empty dict (keys with `None` values) even when `fetch_instance_json` returned `None`. So `if dynamic and ...` is always true, and on instance failure the handler still writes `videos` (with DB fallback values), bumps `last_checked_at`, writes `channels`, and clears `instances.last_error`.\n- Defect: `to_tags_json` returns `None` for an empty list, so a source that removed all tags never propagates. `extract_category` drops a category that has only an `id`.\n- The `/api/video` response does not include tags, category, nsfw, language, duration or thumbnail.\n- There is no `language` column in any schema (crawler `engine/crawler/schema.sql`, whitelist `engine/server/db/jobs/whitelist_migrations.py`, `engine/server/db/jobs/sync-whitelist.py`). `duration`, `thumbnail_url`, `nsfw`, `tags_json` and `category` exist in both.\n- The crawler (`engine/crawler/src/videos-worker.ts` `extractCategory`) stores the category label, or `String(id)` when no label exists, so DB rows can hold numeric category strings such as \"15\".\n- No active test covers `/api/video` today.\n\n### R1 \u2014 Successful-refresh rule (a fix to current behaviour)\n\n- A refresh is successful exactly when the video detail fetch `/api/v1/videos/{id}` returns a JSON object (dict).\n- The existing fetch contract stays as it is: `urlopen(..., timeout=8)`, catching `HTTPError`, `URLError`, `TimeoutError`, and a non-200 status returning `None`. In addition, a body that is not valid JSON, or valid JSON that is not an object, is treated as failure (returns no data) instead of raising out of the handler.\n- A failure of the secondary channel-detail fetch (`/api/v1/video-channels/{slug}`) does not make the refresh unsuccessful. The channel fields then fall back as they do today.\n- On success: one transaction UPDATEs the `videos` row (fields per R2, plus `popularity` and `last_checked_at = now`), UPDATEs the `channels` row as today, and resets `instances.last_error`, `last_error_at` and `last_error_source` for the host. The existing `sqlite3.OperationalError` catch-and-log is kept.\n- On failure: no UPDATE to `videos`, `channels` or `instances` runs at all. `last_checked_at` is unchanged, `instances.last_error` is unchanged, and the response is built field by field from the DB row.\n\n### R2 \u2014 Field mapping rules (one write path)\n\nThere is a single UPDATE path in the handler. For each mutable field, a value present and valid in the source payload overwrites the DB value. A value that is absent, null or invalid keeps the DB value, both in the response and in what is written.\n\n- `title`: source `name` (or `title`), a non-empty trimmed string; otherwise keep DB.\n- `description`: source `description`, a non-empty trimmed string; otherwise keep DB. An empty string keeps DB (current `pick_text` behaviour, deliberately kept).\n- `views`, `likes`, `dislikes`: int-like source values (existing aliases `viewsCount`/`views_count`, etc.); otherwise keep DB.\n- `tags_json`: if source `tags` is a list, overwrite with the JSON array of its string elements. An empty list is stored as `\"[]\"` so removals propagate. If `tags` is absent or not a list, keep DB.\n- `category`: source `category` object \u2192 its `label` (or `name`) if non-empty, else its `id` as a string. A plain string or number is stored as a string. Absent/null keeps DB.\n- `language` (new column): source `language` object \u2192 its `id` (the PeerTube language code, e.g. `\"en\"`). A plain string is stored as is. Absent/null or a null id keeps DB.\n- `nsfw`: source boolean/int-like \u2192 0/1 (existing `to_nullable_bool`); absent/null keeps DB.\n- `duration`: source `duration`, int-like seconds; otherwise keep DB.\n- `thumbnail_url`: source `thumbnailUrl`, else `thumbnailPath`, resolved to an absolute `https://{host}...` URL (existing `resolve_asset_url`); otherwise keep DB.\n- `popularity`: recomputed from the merged views/likes as today, written only on success.\n- `last_checked_at`: set to now only on success.\n\nA partial source response (for example, stats present but tags/category missing) must never wipe the stored tags or category.\n\n### R3 \u2014 Language column (schema change across producers)\n\n- Add `language TEXT` (nullable) to the `videos` table in `engine/crawler/schema.sql`. The crawler DB layer (`engine/crawler/src/db.ts`, including its videos insert/upsert and the `videos_new` rebuild) and `engine/crawler/src/videos-worker.ts` must extract and persist `language` from the PeerTube video payload using the same rule as R2 (the language id/code).\n- Add `language` to the server whitelist `videos` schema through a new migration in `engine/server/db/jobs/whitelist_migrations.py` that is safe on existing databases (additive column). `engine/server/db/jobs/sync-whitelist.py` must create and copy the column.\n- `fetch_video_row` selects `v.language`.\n- Rebuild the committed crawler `dist/` JS if the repository keeps it in sync with `src/` (`engine/crawler/dist/db.js`, `videos-worker.js`).\n\n### R4 \u2014 Category and language display labels\n\n- A static, stdlib-only map in the server holds PeerTube's default video categories (ids 1\u201318 \u2192 labels, e.g. 1 Music, 2 Films, 3 Vehicles, 4 Art, 5 Sports, 6 Travels, 7 Gaming, 8 People, 9 Comedy, 10 Entertainment, 11 News & Politics, 12 How To, 13 Education, 14 Activism, 15 Science & Technology, 16 Animals, 17 Kids, 18 Food) and PeerTube's default language codes \u2192 labels.\n- When `/api/video` builds its response, a stored category that is a digit-only string resolves through the map to its label. Any other stored value is shown as is. An unknown id is shown as the raw value. A stored language code resolves to its label; an unknown code is shown as the raw code.\n- Named simplification: this map covers only PeerTube's defaults. Instances with plugin-added or renamed categories/languages display the raw id or code. Upgrade path: fetch and cache the instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`.\n\n### R5 \u2014 `/api/video` response contract\n\nAll existing response keys are kept unchanged. New keys, each from the merged value (source on success, else DB):\n\n- `tags`: a list of strings parsed from `tags_json` (empty list when null, empty, or unparseable).\n- `category`: the display label per R4, or `\"\"`.\n- `language`: the display label per R4, or `\"\"`.\n- `nsfw`: boolean or `null`.\n- `duration`: integer seconds or `null`.\n- `thumbnailUrl`: string or `\"\"`.\n\nThe Client backend proxy (`client/backend/server.py`, `/api/video` in `PROXY_READ_GET_ROUTES`) passes the body through, and must continue to do so with the new keys.\n\n### R6 \u2014 Video page UI\n\n- In the existing metadata area of `client/frontend/video-page.html` (near `video-meta-row` / `video-description`), add a compact metadata block that shows:\n  - the category label (hidden when empty),\n  - the language label (hidden when empty),\n  - tags as chips, with the empty state \"No tags\" when the list is empty.\n- `client/frontend/src/pages/video-page/index.ts`: extend `VideoMetadata` with `tags`, `category` and `language`. Fill them in `fetchVideoMetadataFromServer` from the new response keys, and in the instance-direct fallback `fetchVideoMetadataFromInstance` from the PeerTube payload (`tags` list, `category.label`, `language.label`). Render them in `loadVideo`. All values are HTML-escaped (existing `escapeHtml`) or set via `textContent`.\n- Styling goes in `client/frontend/src/video.css`, compact and consistent with the existing metadata styles. Rebuild `client/frontend/dist` if the repository keeps it committed.\n\n### R7 \u2014 Tests (active suite, `tests/active`)\n\nA new test module for the `/api/video` handler. It uses a SQLite DB created from the production server (whitelist) `videos`/`channels`/`instances` schema, not a hand-picked column subset, and stubs the instance fetch (`fetch_instance_json`) with no network access. It covers:\n\n- Success fixture: after one request, the DB row holds the source `title`, `description`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, `language`, `duration`, `thumbnail_url`, and a `last_checked_at` newer than before. `instances.last_error`, `last_error_at` and `last_error_source` are reset to NULL. The response carries the new keys per R5.\n- Instance-fail fixtures: at least one each for a caught network error (e.g. `URLError`/`TimeoutError`, via the stub returning `None`) and a malformed/non-object body. Assert every `videos` column is unchanged (no overwrite, `last_checked_at` unchanged), the `channels` row is unchanged, `instances.last_error` is still set, and the response values equal the DB values.\n- Partial-response regression: a source payload with stats but no `tags` and no `category` keeps the stored `tags_json` and `category`. A payload with `tags: []` stores `\"[]\"` and returns `tags: []`.\n- Integration: a source metadata change (e.g. new title and tags) between two requests is reflected in the second `/api/video` response and in the DB.\n- Label mapping: a stored digit-only category (e.g. `\"15\"`) is returned as its label (\"Science & Technology\"); an unknown id is returned raw; a language code is returned as its label.\n- Crawler: `language` is persisted by the crawler videos path (extend `tests/active/test_videos_worker.py`, which already builds from `engine/crawler/schema.sql`).\n- Whitelist migration: the new migration adds `language` to an existing DB without losing rows.\n\nManual validation (not automated): tags, category and language render on the video page, and the \"No tags\" empty state shows for a video without tags.\n\n### Out of scope\n\n- Fetching per-instance category/language lists (R4 upgrade path).\n- Changing the refresh cadence or adding caching of `/api/video`.\n- Displaying nsfw, duration or thumbnail on the video page (they are refreshed, stored and returned, but R6 renders only category, language and tags).\n</requirements>\n\n<conflicts>\nRequest \"keep the current fallback \u2026 DB update and instances.last_error reset run only on a successful refresh\" vs engine/server/api/handlers/video.py: fetch_instance_video_dynamic always returns a non-empty dict, so `if dynamic and instance_domain and row.get(\"video_id\")` is true on failure too and the handler currently writes videos/channels, bumps last_checked_at and clears instances.last_error after a failed fetch. This is a fix, not preservation (R1).\nRequest \"refresh tags\" and regression \"do not wipe tags on partial responses\" vs video.py to_tags_json: an empty source tag list becomes None and falls back to the DB, so tag removals never propagate. Resolved in R2 as absent \u2192 keep, empty list \u2192 \"[]\".\nRequest \"optionally language\" vs the schema: no language column exists in engine/crawler/schema.sql, whitelist_migrations.py or sync-whitelist.py. The operator chose to include it, which requires the schema/crawler/sync changes in R3.\nRequest \"a numeric source category maps to a display label consistently\" vs engine/crawler/src/videos-worker.ts extractCategory storing String(id) and video.py extract_category dropping id-only categories. Resolved by the static default-category map in R4 (operator choice), with the named ceiling for custom instance categories.\nRequest \"keep \u2026 catching HTTPError/URLError/TimeoutError\" vs fetch_instance_json: json.loads on a malformed body raises out of the handler (500). R1 widens failure to include malformed/non-object JSON, which goes beyond the three named exceptions.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe work falls into four parts, each confined to the files the requirements name: the handler, the schema, the page and the tests. What follows was checked against `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, the crawler's `schema.sql`, `db.ts` and `videos-worker.ts`, the video page sources and `tests/active`.\n\n**1. Handler: one success signal, one merge, one write (R1, R2, R5)** in `engine/server/api/handlers/video.py`.\n\n- **`fetch_instance_json`** keeps its contract: `urlopen(..., timeout=8)`, the same three caught exceptions, and a non-200 status still returns `None`. Two cases are added, both logged at info like the network failures:\n  - a body that fails to decode or parse (`ValueError`, which covers both `JSONDecodeError` and `UnicodeDecodeError`) returns `None`;\n  - a parsed value that is not a `dict` returns `None`.\n- **`fetch_instance_video_dynamic`** returns `None` when the detail fetch gives no dict. That is the single success signal R1 defines. The channel-detail fetch keeps its current fallback, so its failure never turns a refresh into a failure.\n  - Presence is kept distinct from emptiness. `tags` is no longer coerced with `or []`, so a missing key and an empty list stay different.\n  - `to_tags_json` returns `\"[]\"` for an empty list and `None` only when the value is not a list.\n  - `extract_category` falls back to `str(id)` when the object has no label, and turns a number into a string.\n  - A small `extract_language` returns the object's `id` (or a plain non-empty string). A null id returns `None`.\n  - `duration` goes through `pick_number`. `thumbnail_url` goes through `resolve_asset_url(host, thumbnailUrl or thumbnailPath)`.\n  - A `None` in the dynamic dict always means \"keep the DB value\".\n- **`fetch_video_row`** also selects `v.language`, `v.duration` and `v.thumbnail_url`. The last two are needed so the fallback response can serve them from the DB.\n- **`handle_video_request`** builds one merged set of values:\n  - each field is the source value when it is present and valid, otherwise the DB value, using the existing `pick_text`/`pick_number`/None-check rules;\n  - that one set feeds both the response and the UPDATE, so the two can never disagree;\n  - when `dynamic is None` (fetch failed, or no host), the merged values are just the DB row and the whole write block is skipped. No `videos`, `channels` or `instances` statement runs;\n  - on success the existing single transaction runs with the SET list extended by `language`, `duration` and `thumbnail_url`, plus `popularity` and `last_checked_at`. The `channels` update and the `instances.last_error*` reset stay as they are, and so does the `OperationalError` catch.\n- **Response.** Every existing key is kept, plus:\n  - `tags`: parsed from the merged `tags_json`, keeping string elements only, and `[]` on null, empty or unparseable;\n  - `category` and `language`: display labels (see part 2), or `\"\"`;\n  - `nsfw`: a bool or `null`;\n  - `duration`: an int or `null`;\n  - `thumbnailUrl`: a string or `\"\"`.\n- **Client proxy.** `client/backend/server.py` needs no change: `/api/video` is in `PROXY_READ_GET_ROUTES`, which passes the body through.\n\n**2. Display labels (R4).** A new stdlib-only module, `engine/server/data/peertube_labels.py`, holds two dicts:\n\n- PeerTube's default categories: `\"1\"`\u2013`\"18\"` mapped to labels, exactly as listed in R4.\n- PeerTube's default language codes mapped to labels, copied once from a stock instance's `/api/v1/videos/languages` output and committed as a literal dict.\n\nIt has two tiny lookup functions:\n- category: a digit-only string resolves through the map; any other value, or an unknown id, is returned as it is;\n- language: a known code resolves to its label; an unknown code is returned raw.\n\nThe handler uses them only when it builds the response. Stored values are never rewritten to labels, so FTS and embeddings keep what the crawler writes today.\n\n**3. `language` column across the producers (R3).**\n\n- **Crawler (`engine/crawler`):**\n  - `schema.sql` gets `language TEXT` after `category`.\n  - `db.ts`:\n    - an additive step in `applyBaseSchema` runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. This is required: `CREATE TABLE IF NOT EXISTS` never adds columns, and without it every existing `crawl.db` fails `sync-whitelist.py`'s superset check against `schema.sql`;\n    - the `videos_new` rebuild in `migrateVideos` carries `language`, with the same conditional-expression pattern (`hasLanguage ? \"language\" : \"NULL\"`) it uses for the error columns;\n    - `VideoUpsertRow` gains `language`, and the upsert gains the column in its INSERT list, in `ON CONFLICT ... language = excluded.language`, and in the positional `run(...)` arguments.\n  - `videos-worker.ts`: `PeerTubeVideo` gains a `language` field, a new `extractLanguage` follows R2's rule (object \u2192 `id`; non-empty string \u2192 itself; otherwise `null`), and `toVideoRow` sets it.\n  - `dist/db.js` and `dist/videos-worker.js` are rebuilt with `npm run build` and committed. `test_videos_worker.py` asserts the dist is not stale.\n- **Server whitelist DB:**\n  - `sync-whitelist.py`: `ensure_content_schema`'s `CREATE TABLE videos` gets `language TEXT`. Copying needs nothing more, because `VIDEO_COLUMNS` is parsed from `schema.sql`, so both `rebuild_content_tables` and `ensure_schema_compatibility` pick the column up automatically.\n  - `whitelist_migrations.py`: a new `migrate_videos_language(conn)` checks `_columns` and, if the column is missing, runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is idempotent, keeps every row, and leaves the FTS triggers alone because they do not reference `language`. `migrate_whitelist_schema` calls it after `migrate_videos_schema`, so even a DB that needed the old rebuild ends up with the column.\n  - The Python `videos_new` rebuild also carries `language` conditionally. That way no rebuild path can drop it.\n- **Updater worker:** `updater-worker.py` merges through `shared_columns`, which works by column name, so it needs no change.\n\n**4. Video page (R6).**\n\n- `video-page.html`: a compact `video-taxonomy` block goes between `video-meta-row` and `video-description`. It holds a category span, a language span and a tags container.\n- `index.ts`:\n  - `VideoMetadata` gains `tags: string[]`, `category: string` and `language: string`;\n  - `fetchVideoMetadataFromServer` fills them from the new keys, keeping only string elements of `tags`;\n  - `fetchVideoMetadataFromInstance` fills them from the PeerTube payload (`tags` list, `category.label`, `language.label`);\n  - `loadVideo` renders them with `textContent` and `createElement` for the chips, so no HTML is interpolated. Category and language are hidden when empty, and the tag list shows \"No tags\" when it is empty.\n- `video.css` gets compact chip and label styles that reuse the existing metadata sizes and colours.\n- `client/frontend/dist` is committed, so it is rebuilt.\n\n**5. Tests (R7).**\n\n- **New `tests/active/test_video_handler.py`.**\n  - It loads `sync-whitelist.py` with `spec_from_file_location` (the precedent in `test_repair_video_channel_names.py`) and builds a `tmp_path` DB with its `ensure_whitelist_schema` + `ensure_content_schema`. That is the production schema, triggers included.\n  - It imports `handlers.video` with `engine/server` and `engine/server/api` on `sys.path`.\n  - The server is a `SimpleNamespace` with `db` (row factory `sqlite3.Row`), `db_lock`, `video_error_threshold` and `popularity_like_weight`. `respond_json` is monkeypatched to capture the status and body.\n  - **Fetch stubs, no network:**\n    - `fetch_instance_json` is replaced with a path-keyed fake for the success, partial-payload, integration and label cases, and returns `None` for the network-error case;\n    - for the malformed-body cases, `video.urlopen` is replaced with a fake response carrying a non-JSON body and a JSON list, and with one that raises `URLError`. This exercises the real parse guard.\n  - **Cases:** success, network failure, malformed body, a partial payload keeping tags and category, `tags: []` \u2192 `\"[]\"` / `[]`, two sequential requests with changed source data, and the label mapping (`\"15\"` \u2192 \"Science & Technology\", unknown id raw, language code \u2192 label).\n  - **Failure assertions:** a snapshot of the whole `videos` row and the whole `channels` row, taken with `SELECT *` before and after, so every column is compared, not a chosen subset.\n- **Migration test.** It builds a legacy `videos` table inline with the pre-change columns (the old shape can only be written out, since the current helpers will create the new one), inserts rows, runs `migrate_whitelist_schema`, and asserts the column exists, the rows are intact, and a second run is a no-op.\n- **`test_videos_worker.py`.** The stand-in payload gains `language: {id: \"en\", label: \"English\"}` and the test asserts the stored `language`. A second case pre-creates a `crawl.db` without the column, to prove the additive crawler migration.\n\n### Alternatives considered\n\n- **Success signal.** One option is a sentinel or exception from `fetch_instance_video_dynamic`, another is having it return `(ok, data)`. Returning `None` on detail failure is the smallest change and matches how `fetch_instance_json` already reports failure. Checking for \"any non-None field\" was rejected: a valid source that lacks every optional field would then count as a failure.\n- **Two write paths (stats-only vs full).** Rejected, because R2 requires a single UPDATE path. With a single merge, \"keep DB when absent\" is just \"write back the DB value\", which leaves the row unchanged.\n- **Storing labels instead of ids for language.** Rejected, because R2 fixes the stored value as the code. Resolving at response time keeps the map an honest display concern and lets the upgrade path (per-instance lists) plug in without a data migration.\n- **Label map placement.**\n  - Inline in `video.py`: rejected, because a ~200-entry language table would bury the handler.\n  - A JSON data file: rejected, because it adds a load step and a file path for no gain over a Python literal.\n  - One small module is the minimum.\n- **Migrating the whitelist DB at Engine startup.** Rejected. The conftest `engine` fixture starts the Engine against the repo's live `engine/server/db/whitelist.db`, so a startup `ALTER TABLE` would change a shared DB from a worktree test run. The migration stays in `migrate-whitelist.py`, the existing operator path. The same applies to the crawler's migration, which only runs when the crawler opens its own DB.\n- **Adding `language` to `videos_fts`.** Not required, and it would force an FTS rebuild. Left out.\n- **Malformed-body test through `fetch_instance_json` stubs only.** Rejected. A stub that returns a list would test only the handler, not the new parse guard, so those cases stub `urlopen` one level lower.\n\n### Gotchas and risks\n\n- **Deployment order.** After the merge, `fetch_video_row` selects `v.language`. An Engine started on an unmigrated `whitelist.db` answers every `/api/video` with a 500. `sync-whitelist.py` likewise refuses an unmigrated whitelist DB (the exact column check, with the existing \"run migrate-whitelist.py\" message) and an un-upgraded `crawl.db` (the superset check). The runbook order is:\n  1. merge;\n  2. run the crawler once, or open `crawl.db` with it, so the additive migration runs;\n  3. run `migrate-whitelist.py` on every `whitelist.db`, the prod one included;\n  4. restart the Engine.\n  \n  This goes in `DATA_BUILD.md` / the harvest notes.\n- **Unset category shows \"Unknown\".** When no category is set, PeerTube returns `{id: null, label: \"Unknown\"}`. R2 takes the label whenever it is non-empty, so such videos store and show \"Unknown\". The crawler already stores it today, so the data does not change, but the page will now show \"Unknown\" as a category and the instance-direct fallback will do the same through `category.label`. Language behaves differently: a null id keeps the DB value, so an unset language stays hidden.\n- **A removed language never propagates.** PeerTube reports \"unset\" as a null id, which R2 treats as \"keep DB\". The same holds for a description cleared to `\"\"` (deliberately kept `pick_text` behaviour) and for title.\n- **Uncaught fetch errors.** Exceptions outside the kept contract, such as `ConnectionResetError` or `http.client.IncompleteRead`, still propagate as a 500. They are raised before any write, so the rule that stored data never changes on failure still holds. Widening the catch is a one-line follow-up if wanted.\n- **The FTS trigger now fires only on real refreshes.** That is a behaviour improvement, but each successful `/api/video` still rewrites the row's FTS entry, as it does today.\n- **Embeddings go stale.** They are not recomputed when tags or category change through `/api/video`. `build-video-embeddings.py` picks the new values up on its next run, as it does today.\n- **Column order differs.** A fresh DB has `language` next to `category`, while a migrated DB has it last. Every reader I found uses names (`shared_columns`, named INSERT/SELECT lists, `sqlite3.Row`).\n- **The language map is transcribed by hand.** A wrong or missing entry shows the raw code. That is harmless, but it is a fidelity risk.\n- **Dist rebuilds.** Crawler dist needs `engine/crawler/node_modules` (`npm install && npm run build`), because `test_videos_worker.py` fails on a stale dist. The client dist rebuild changes hashed asset names in `dist/video-page.html`.\n\n### Tradeoffs the operator accepts\n\n- **Default-only labels (named simplification, R4).** Categories and languages that an instance adds or renames show as raw ids or codes. The ceiling is PeerTube's stock lists. The upgrade path is fetching and caching `/api/v1/videos/categories` and `/api/v1/videos/languages` per instance.\n- **Manual migration step.** A deploy needs `migrate-whitelist.py` run before the Engine restarts. The build does not migrate automatically, to keep worktree tests off the shared DB.\n- **\"Unknown\" category and asymmetric removal.** A video with no category shows \"Unknown\", and a language removed at the source is not cleared. Both follow R2 literally. Changing either means treating a `null` id as \"cleared\", which is a requirements change.\n- **Failed refresh leaves the error visible.** On failure the page shows DB values with no staleness indicator, and `instances.last_error` stays as the last writer left it. This build does not set a new error.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_json() (lines 75-87)\">\n**What changes:** it keeps `urlopen(req, timeout=8)`, the `(HTTPError, URLError, TimeoutError)` catch and the non-200 \u2192 `None` return. Two new failure paths return `None` and log at info: a `ValueError` from `.decode(\"utf-8\")` or `json.loads` (this covers both `UnicodeDecodeError` and `JSONDecodeError`), and a parsed value that is not a `dict`.\n\n**What depends on it:** `fetch_instance_video_dynamic` calls it twice, once for the detail and once for the channel. The channel call at line 176 already checks `isinstance(channel_detail, dict)`, so returning `None` for a non-dict does not change it. The new test replaces `video.urlopen` to reach this function directly. `urlopen` is imported by name at line 14, so the monkeypatch must target `handlers.video.urlopen`, not `urllib.request.urlopen`.\n\n**Regression risk: low.** Today a malformed body raises `ValueError` out of `do_GET`. `similar.py:438-441` re-raises anything that is not \"interrupted\", so the socket closes with no response and the Client proxy sees a transport error, retries once, then answers 502. After this change the same case becomes a DB-fallback 200. Exceptions outside the contract still drop the connection the same way: `ConnectionResetError`, `http.client.IncompleteRead`, `RemoteDisconnected`, and `ssl.SSLError` if it is not wrapped in `URLError`. The plan's \"500\" wording is inaccurate: there is no 500 handler, the connection just closes. The `# pragma: no cover` on the except line should come off once tests cover it.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_video_dynamic() (lines 162-205)\">\n**What changes:** it returns `None` when the detail fetch does not give a dict; this is the single success signal. `tags` is no longer coerced with `or []`. New keys: `language` (from `extract_language`), `duration` (from `pick_number(detail.get(\"duration\"))`) and `thumbnail_url`.\n\n**Things to get right:**\n- `resolve_asset_url` returns `\"\"`, not `None`, when the value is missing (line 92-93). `thumbnail_url` therefore has to map `\"\"` to `None`, or a payload with no thumbnail overwrites the DB value with `\"\"`. This breaks R2's rule that `None` means \"keep the DB value\".\n- `pick_number` accepts `bool`, because `bool` is a subclass of `int`, so `True` becomes 1. That is harmless for `duration`.\n- `account_avatar_url` is already `\"\"`-defaulted and is only used in the response, which is unchanged.\n- `channel.get(...)` needs `detail.get(\"channel\")` to be a dict. Today it runs `detail.get(\"channel\") or {}`, and a non-dict truthy `channel` (a string, say) would raise `AttributeError`. This is a pre-existing gap and now worth guarding with `isinstance`, because the function runs only on success.\n- Tag strings are not trimmed or deduplicated.\n\n**What depends on it:** only `handle_video_request` (line 227). The grep found no other importer of `handlers.video` apart from `similar.py:84`.\n\n**Regression risk: medium.** This function is the core of R1 and R2. Returning `{}` instead of `None` on failure would reintroduce the \"always truthy\" defect, but only if the caller keeps the `if dynamic` test. The caller must test `dynamic is None`, not truthiness, or a success whose dict happens to be empty would be treated as a failure.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"to_tags_json() (lines 132-137)\">\n**What changes:** a list returns `json.dumps([string elements])`, and an empty list (or a list of only non-strings) returns `\"[]\"`. Anything that is not a list returns `None`.\n\n**What depends on it:** only `fetch_instance_video_dynamic`.\n\n**Downstream effects of `\"[]\"` now being stored in whitelist.db:**\n- The FTS trigger indexes `\"[]\"`, which tokenises to nothing, so it is harmless.\n- `build-video-embeddings.parse_tags(\"[]\")` returns `[]` (line 19-26).\n- The crawler's `listVideosForTags` treats `'[]'` as missing, but it reads crawl.db, not whitelist.db, so it is unaffected.\n\n**Regression risk: low.** `json.dumps` defaults to `ensure_ascii=True`, which is the same as today, so non-ASCII tags are stored `\\u`-escaped. FTS then indexes the escape sequences rather than the words. This is existing behaviour, but it now also applies to refreshed tags, and the crawler (TS `JSON.stringify`) stores raw UTF-8. The build could pass `ensure_ascii=False` to match the crawler. That is a judgment call, so it is flagged here rather than required.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"extract_category() (lines 140-146)\">\n**What changes:** for an object: `label` or `name`, else `str(id)` when the id is not `None`. A number becomes `str(n)`.\n\n**Gap in the current code:** a plain string is returned as-is, including `\"\"` and whitespace. A non-`None` `\"\"` then overwrites the stored category, which R2 forbids (\"absent/null keeps DB\"). Plain strings should go through `pick_text`. Numbers need a `bool` guard (`isinstance(True, int)` is true).\n\n**PeerTube behaviour:** an unset category is `{id: null, label: \"Unknown\"}`, which gives \"Unknown\". That matches the crawler's `extractCategory` (videos-worker.ts:838-848), so the stored value agrees with what the crawler writes.\n\n**Regression risk: low.** Only the dynamic dict uses it.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"new extract_language() helper\">\n**What changes:** a new helper. For an object it returns `id` as a non-empty string; for a plain non-empty string it returns that string; otherwise `None`. A null id (PeerTube's unset `{id: null, label: \"Unknown\"}`) returns `None`, which keeps the DB value.\n\n**What depends on it:** `fetch_instance_video_dynamic`. It should mirror the crawler's new `extractLanguage` so both producers store the same code.\n\n**Regression risk: low.** Watch for `id` given as a non-string. PeerTube language ids are strings such as `\"en\"` or `\"zh-Hans\"`, so use `pick_text` rather than `str()`, so that `0` or `False` never become codes.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_video_row() SELECT (lines 33-69)\">\n**What changes:** it also selects `v.language`, `v.duration` and `v.thumbnail_url`. `duration` and `thumbnail_url` already exist in both schemas (schema.sql:45-46, sync-whitelist.py:366-367), so only `language` needs the migration.\n\n**What depends on it:** `handle_video_request` only. The row goes into `dict(row)`, so it is read by column name, and column order does not matter.\n\n**Regression risk: high (deployment).** On any whitelist.db that has not been migrated, this SELECT raises `sqlite3.OperationalError: no such column: v.language`. It is not \"interrupted\", so `similar.py:438-441` re-raises it and the Engine drops the connection on every `/api/video`. What the browser sees:\n- The Client proxy retries once, then answers 502 `ENGINE_PROXY_UNAVAILABLE`.\n- `fetchVideoMetadataFromServer` returns null, and the page falls back silently to the instance-direct fetch. The failure is visible only in the logs.\n- `tests/run-arch-split-smoke.sh:582` and `run-installers-smoke.sh:647` assert 200 and will fail.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request(): merge block (lines 226-258) and write block (lines 292-358)\">\n**What changes:** one merged value set feeds both the response and the UPDATE.\n- `dynamic is None` (fetch failed, or `instance_domain` is empty, which today gives `{}` at line 227) skips the whole write block.\n- On success the UPDATE SET list gains `language`, `duration` and `thumbnail_url`.\n\n**Things to keep:**\n- The merge currently uses `dynamic.get(\"title\") or row.get(\"title\")`, which is falsy-based. For title and description that is fine, because `pick_text` never returns `\"\"`. For numeric and nullable fields keep the existing `is None` pattern.\n- `channel_display` falls back to `row[\"channel_name\"]`, and the UPDATE writes it into `videos.channel_name`. Keep that.\n- `channels` UPDATE: when `channel_slug` is `None` (no channel in the payload and no `channel_slug` from the join), it writes `channel_name = NULL`. Today it runs on failure too; on success only it still can. This is pre-existing and should be flagged, not changed.\n- The `instances` reset runs even when no `instances` row exists for the host; it is a no-op.\n- `popularity`: `compute_popularity(views, likes, row[\"published_at\"], ...)`. Keep it.\n\n**Transaction:** `with server.db_lock: with server.db:` commits or rolls back as one unit, so the `OperationalError` catch leaves nothing half-written.\n\n**What depends on it:** `similar.py:495-497`. The `videos_fts_au` trigger fires on every successful UPDATE, including no-op field sets. `last_checked_at` is always bumped on success, so every successful request rewrites the row's FTS entry. That is today's behaviour, now limited to successes.\n\n**Regression risk: high.** This is the heart of R1 and R2. Today a failure still writes: it bumps `last_checked_at`, clears `instances.last_error`, and can set `channels.channel_name` to NULL. After the change, failures stop all of that, and any operational process that relied on those side effects loses them. None was found by grep.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"response dict (lines 271-290)\">\n**What changes:** all 18 existing keys are kept. New keys:\n- `tags`: parse the merged `tags_json`, keep string elements only, and give `[]` on NULL, `\"\"`, invalid JSON or a non-list.\n- `category`: label via `peertube_labels`, or `\"\"`.\n- `language`: label, or `\"\"`.\n- `nsfw`: `bool(int)`, or `None`. Stored 0/1 becomes `False`/`True`.\n- `duration`: int, or `None`. The stored INTEGER passes through.\n- `thumbnailUrl`: string, or `\"\"`.\n\n**What depends on it:**\n- The Client proxy passes the body through as bytes (`client/backend/server.py:606-619`).\n- `index.ts fetchVideoMetadataFromServer` reads only the keys it knows, so the extra keys are harmless to the current build.\n\n**Regression risk: low.** `tags_json` from the crawler can hold a JSON string rather than a list, which `build-video-embeddings.parse_tags` tolerates by treating it as one tag. The response parser should return `[]` for a non-list, as R5 says. Note that this differs from `parse_tags` on the same input.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"helpers resolve_asset_url, pick_text, pick_number, to_nullable_bool (lines 90-159)\">\n**What changes:** nothing. Their contracts matter to the merge:\n- `resolve_asset_url` returns `\"\"` on a missing value and always uses `https://`, while the crawler's `resolveAssetUrl` keeps the crawl protocol and adds a `/` when there is none.\n- `pick_text` trims.\n- `pick_number` truncates floats and accepts `bool`.\n- `to_nullable_bool` maps an unknown type to `None`.\n\n**Regression risk:**\n- A refreshed `thumbnail_url` may differ in form from the crawler's (`thumbnailPath` against the crawler's `thumbnailUrl ?? thumbnailPath ?? thumbnail_path ?? thumbnail`). The plan picks `thumbnailUrl or thumbnailPath` only. A PeerTube payload with only `thumbnail_path` or a `thumbnail` object keeps the DB value. That is safe.\n- A relative path with no leading `/` gives `https://hostpath`, which is malformed. PeerTube always sends a leading `/`, so this is low risk.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"do_GET statement_deadline (lines 433-441), _dispatch_get /api/ rate limit (447-449), /api/video route (495-497)\">\n**What changes:** nothing in code, but this interaction was not in the plan.\n\n**Deadline:** `/api/video` runs inside `statement_deadline(statement_timeout_seconds)`, 5 s by default. The deadline is an absolute thread-local time set at request start (`data/db.py:44-64`). The two outbound fetches (up to 8 s + 8 s) run before the UPDATE, so for any instance slower than about 5 s in total:\n- the UPDATE, and the triggers it fires, raise `OperationalError('interrupted')`;\n- the handler's existing catch logs a warning and answers 200 with the fresh values, but nothing is persisted.\n\nA slow instance can therefore never be refreshed in the DB. This is today's behaviour as well, and the handler's `OperationalError` catch is what keeps it a 200. The new tests use a `SimpleNamespace` server with no deadline, so they will not show this.\n\n**Rate limit:** `/api/` routes, `/api/video` included, go through the Engine's 60/min per-IP limiter. The earlier assumption that it is not rate-limited is wrong. A 429 is answered before the handler runs.\n\n**What depends on it:** every `/api/video` request.\n\n**Regression risk: medium (latent).** The DB-write guarantee is best-effort for slow sources. Document it; widening the deadline is out of scope.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"statement_deadline / install_deadline_handler / connect_db (lines 31-81)\">\n**What changes:** nothing.\n\n**What depends on it:** `server.db` carries the progress handler. The new handler test builds its own `sqlite3.connect` without it, so it runs with no deadline.\n\n**Regression risk:** none from the build. The test cannot cover the deadline behaviour described in the `similar.py` entry.\n</impact>\n<impact path=\"engine/server/data/peertube_labels.py\" element=\"new module: category map, language map, two lookup functions\">\n**What changes:** a new stdlib-only module holding:\n- `CATEGORY_LABELS`: `\"1\"`\u2013`\"18\"`, exactly R4's list, including `\"11\": \"News & Politics\"`, `\"12\": \"How To\"` and `\"15\": \"Science & Technology\"`.\n- a language-code map copied from stock PeerTube.\n- a category lookup: digit-only strings go through the map, and anything else or an unknown id is returned unchanged.\n- a language lookup: known codes resolve, and unknown codes are returned raw.\n\nIt follows the `engine/server/data/*.py` style (a module docstring, `from __future__ import annotations` as in `whitelist_migrations`), with a docstring on every function.\n\n**What depends on it:** the video.py response builder only, which imports it as `from data.peertube_labels import ...`, matching the existing `from data.time import now_ms`.\n\n**Regression risk: low.**\n- The map is transcribed by hand, so there is a fidelity risk.\n- PeerTube language codes are case-sensitive (`zh-Hans`, `zh-Hant`, `pt-PT`), so the lookup must not lowercase.\n- Use `str.isdigit()` together with `isascii()`, or a Unicode digit such as `\"\u0661\u0665\"` counts as digit-only. Harmless, since the result is an unknown id returned raw.\n- The Engine imports `data.*` at startup, so the module must do no work at import beyond the literals.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"PROXY_READ_GET_ROUTES / PROXY_ALLOWED_QUERY_PARAMS['/api/video'] (lines 81-88) and _proxy_engine_request (570-680)\">\n**What changes:** nothing. The body is passed through as bytes, and `row_filter` is `None` for `/api/video`.\n\n**What depends on it:** the page. `ENGINE_PROXY_TIMEOUT_SECONDS = 10` with `ENGINE_PROXY_RETRY_COUNT = 1`. The Engine's `/api/video` can take up to 16 s on a slow source, which exceeds the proxy timeout. The proxy then retries, so a second Engine request (and possibly a second write) runs for the same page view. This is pre-existing; it is noted because each successful request now writes more columns.\n\n**Regression risk: none from the code.** An unmigrated DB turns into a 502 here, as described in the `fetch_video_row` entry.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"videos CREATE TABLE (lines 29-61)\">\n**What changes:** `language TEXT` is added after `category` (line 42).\n\n**What depends on it:**\n- `sync-whitelist.py` parses the column list at import (lines 92-96), so `VIDEO_COLUMNS` gains `language`. This drives the exact check against the whitelist DB, the superset check against crawl.db, and the copy column list.\n- `db.ts` runs `schemaSql` twice in `applyBaseSchema`.\n- `updater-worker.init_staging_db` creates staging from it (lines 548-565).\n- `tests/active/test_videos_worker.py` and `test_repair_video_channel_names.py` build crawl-shaped DBs from it.\n\n**Regression risk: medium.** `CREATE TABLE IF NOT EXISTS` never adds the column to an existing crawl.db. The first `db.exec(schemaSql)` in `applyBaseSchema` also runs every `CREATE INDEX` against the old table, so no index on `language` may be added to schema.sql, or the first exec fails on old DBs before the migration can run. The parser splits on top-level commas; a plain `language TEXT,` line parses cleanly.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"applyBaseSchema() (lines 65-71): new additive language step\">\n**What changes:** after `migrateVideos(db)` and before the second `db.exec(schemaSql)`, a step checks `getColumns(db, \"videos\")` and runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. It must run after `migrateVideos`, so that a rebuilt table is also covered, and it must be guarded with `tableExists`.\n\n**What depends on it:** every store constructor: `CrawlerStore` (line 520), `ChannelStore` (792) and `VideoStore` (1203). Any crawler CLI that opens crawl.db migrates it: instances, channels, videos, counts. `openExistingDb` (videos-worker.ts:940) opens the prod DB read-only with no migration, and only reads `video_id`, so it is safe.\n\n**Regression risk: medium.** It is the only way an existing crawl.db can pass `sync-whitelist`'s superset check. `ALTER ADD COLUMN` is a cheap metadata change, but it needs a write lock, and a concurrently running crawler process sharing crawl.db will contend. The column lands last on migrated DBs; all readers use column names.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"migrateVideos() rebuild (lines 277-399)\">\n**What changes:** a `hasLanguage` flag and a `languageExpr` (`\"language\"` or `\"NULL\"`); `language TEXT` in the `videos_new` CREATE; `language` in the INSERT and SELECT column lists.\n\n**What depends on it:** only very old crawl.db files that lack the error columns reach this rebuild.\n\n**Regression risk: low.** The column lists here are positional pairs, so an INSERT/SELECT that is out of step would silently shift data. Keep the three lists aligned.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"VideoUpsertRow (lines 465-491), VideoStore upsertStmt (1138-1196), upsertVideos (1453-1487)\">\n**What changes:** a `language: string | null` field. The INSERT column list gains `language`. The VALUES list grows from 25 to 26 `?`, and must stay aligned with `NULL, NULL, 0` for the error columns. The ON CONFLICT clause gains `language = excluded.language`, and the positional `run(...)` gains `row.language` at the matching position.\n\n**What depends on it:** `toVideoRow` builds the row.\n\n**Regression risk: medium.**\n- A positional mismatch between the column list, the `?` count and the `run()` arguments shifts every column after it. SQLite reports a count mismatch as an error, but not a mis-ordering.\n- **Behaviour:** `language = excluded.language` makes a re-crawl overwrite the stored language with NULL when the listing payload carries `{id: null}`. That is consistent with how the crawler treats `category`, but it differs from the handler's \"null keeps DB\" rule. A crawl can therefore erase a language the Engine learned. Only crawl.db is affected; whitelist.db is rebuilt from it by sync, see the sync entry.\n- `listExistingVideoIds` and `--new-videos` skip videos that already exist, so updater crawls never fill in `language` for existing rows. Existing rows get a language only from a full re-crawl or from `/api/video` views (whitelist.db only).\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"listVideosForTags / updateVideoTags / updateVideoInvalid / updateVideoError (lines 1283-1539)\">\n**What changes:** nothing.\n\n**What depends on it:** the tags enrichment writes only `tags_json`, so language is not touched.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"PeerTubeVideo interface (lines 84-118), new extractLanguage(), toVideoRow() (lines 648-709)\">\n**What changes:**\n- `PeerTubeVideo` gains `language?: PeerTubeLanguage | string`, where `PeerTubeLanguage` is `{ id?: string | null; label?: string }`, modelled on `PeerTubeCategory` at lines 78-82.\n- `extractLanguage`: an object gives `id` via `toNullableString`, a string gives itself via `toNullableString`, anything else gives `null`. It is placed next to `extractCategory` in the same style and carries a docstring comment.\n- `toVideoRow` sets `language: extractLanguage(video.language)`.\n\n**What depends on it:** `crawlChannelVideos` \u2192 `upsertVideos`. The PeerTube channel-videos listing does include `language`, so it is captured on the normal crawl path.\n\n**Regression risk: low.** Match the handler's rule exactly, including that a numeric id gives `null`. `toNullableString` rejects numbers, which is consistent with the handler using `pick_text`.\n</impact>\n<impact path=\"engine/crawler/dist/db.js\" element=\"compiled db module (VideoStore upsert line ~1100+, migrateVideos ~268, applyBaseSchema)\">\n**What changes:** regenerated by `npm run build` (`tsc -p tsconfig.json`) and committed with the source.\n\n**What depends on it:** production runs the dist, not the source. That covers `updater-worker.py` through `dist/videos-cli.js` (lines 952-982), `npm run crawl:*` and `run-dataset-build.sh`, plus `test_videos_worker.py`.\n\n**Regression risk: medium.** `test_videos_worker._dist_is_stale` compares only `videos-worker.ts` with `videos-worker.js`. A stale `db.js` is not caught by the staleness gate. It would show up only as `language` missing from the upsert (the new assertion) or as a superset-check failure later. Rebuild and commit both, and check the diff.\n</impact>\n<impact path=\"engine/crawler/dist/videos-worker.js\" element=\"compiled crawlVideos / toVideoRow / extractLanguage\">\n**What changes:** regenerated and committed.\n\n**What depends on it:** `test_videos_worker.py` imports it, and its staleness gate checks this pair.\n\n**Regression risk: medium, for the suite.** The rebuild needs `engine/crawler/node_modules` (typescript and better-sqlite3). `tsc` recompiles all of `src/`, so any other dist file already out of step (for example `host-filters.js`, which `test_host_normalisation.py` checks) will change in the same commit. Review the full dist diff.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"ensure_content_schema() CREATE TABLE videos (lines 350-383)\">\n**What changes:** `language TEXT` after `category`.\n\n**What depends on it:**\n- `main()` line 597 on every sync.\n- `test_repair_video_channel_names.py:70,134` builds its whitelist shape from this.\n- The new handler test and the migration test build from it.\n- `repair-video-channel-names.py` loads the module lazily.\n\n**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` does nothing on an existing whitelist.db, so the column on existing DBs comes only from the migration. The exact check then enforces it (next entry).\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"VIDEO_COLUMNS (line 96), ensure_schema_compatibility() (186-216), rebuild_content_tables() (448-522)\">\n**What changes:** nothing in code. `language` flows in from schema.sql.\n\n**Behaviour:**\n- The exact check (`VIDEO_COLUMNS + [\"popularity\"]`) rejects an unmigrated whitelist.db with \"missing columns: language ... Run migrate-whitelist.py\".\n- The superset check rejects a crawl.db the crawler has not opened with \"Update the crawl DB ...\".\n- The copy (`INSERT INTO videos (cols) SELECT cols FROM source.videos`) uses column names, so order does not matter.\n\n**Regression risk: medium (operational).**\n- `rebuild_content_tables` runs `DELETE FROM videos` and reloads from crawl.db. Every `/api/video` refresh in whitelist.db (tags, category, language, `last_checked_at`) is therefore thrown away on the next sync, unless the crawler has since stored the same values. The \"persisted\" metadata lasts only until the next dataset build. This is pre-existing for the other fields, and it now matters for `language` because crawl.db rarely has it for existing rows.\n- `scripts/run-dataset-build.sh:227-228` runs sync against an existing whitelist.db without migrating it first, so the first build after merge fails at the exact check until `migrate-whitelist.py` has run.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"VIDEOS_FTS_TRIGGERS_SQL / ensure_content_schema videos_fts (lines 270-417)\">\n**What changes:** nothing. The FTS index and the triggers cover `title, description, tags_json, category, channel_name`, not `language`, which is the plan's decision.\n\n**What depends on it:** the handler's UPDATE fires `videos_fts_au`.\n\n**Regression risk: none.** `ALTER TABLE ADD COLUMN` on `videos` leaves the triggers and the external-content FTS valid.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"migrate_videos_schema() rebuild (lines 232-370)\">\n**What changes:** it carries `language` conditionally, the same way the error columns are carried: `language TEXT` in `videos_new`, and `language` / `{language_expr}` in the INSERT and SELECT lists.\n\n**What depends on it:** `migrate_whitelist_schema`.\n\n**Regression risk: medium.** This rebuild also runs `DROP TABLE IF EXISTS video_embeddings` and drops `videos_fts` and its triggers (lines 262-266). A migration test whose inline legacy table lacks `last_error`, `last_error_at` or `error_count` takes this destructive path. Build the legacy fixture with the error columns present and only `language` missing, to test the additive path in isolation, or assert the rebuild path on purpose. As with db.ts, the positional lists must stay aligned.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"new migrate_videos_language(conn) and migrate_whitelist_schema() (lines 373-377)\">\n**What changes:** a new function. It returns early if the `videos` table does not exist (`_table_exists`); if `language` is not in `_columns(conn, \"videos\")` it runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is called last in `migrate_whitelist_schema`. Precedent: `recompute-popularity.ensure_popularity_schema` (lines 18-25) does the same kind of additive ALTER.\n\n**What depends on it:** `migrate-whitelist.py:87`, which runs inside `with conn:`.\n\n**Regression risk: low.** It is idempotent. The signature is `migrate_whitelist_schema(conn, table_name)`, so the test must pass `\"instances\"`. The FTS index is left alone: `videos_fts` is external content over named columns.\n</impact>\n<impact path=\"engine/server/db/jobs/migrate-whitelist.py\" element=\"main() (lines 72-91)\">\n**What changes:** nothing in code. It now also adds `language`.\n\n**What depends on it:** the operator runbook. It must run on every whitelist.db (prod, dev, the one symlinked into worktrees) before the new Engine starts. It takes a backup by default (a full file copy of a large DB).\n\n**Regression risk: low (code), high (process).** The step is manual, and forgetting it breaks `/api/video` everywhere and makes `sync-whitelist` refuse to run. It imports `server.db.jobs.whitelist_migrations` with `engine_dir` on the path.\n</impact>\n<impact path=\"engine/server/db/jobs/merge-staging-db.py\" element=\"merge column intersection (lines 142-158) with merge_rules.json videos INSERT_ONLY\">\n**What changes:** nothing.\n\n**Behaviour:** `merge_columns = [c for c in prod_columns if c in stage_columns]`. Staging is created from schema.sql and has `language`. If prod is unmigrated, `language` is silently dropped from the merged new rows, with no error. Because `videos` is INSERT_ONLY, existing prod rows never receive `language` from the updater.\n\n**What depends on it:** the updater cycle.\n\n**Regression risk: low.** It fails soft. It is one more reason to migrate prod first. The plan says \"updater-worker merges through shared_columns\"; the merge that matters is in `merge-staging-db.py`, and `shared_columns` in the updater only seeds `channels`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"init_staging_db (548-565), seed_staging_from_prod / shared_columns (568-619), crawler dist invocation (952-982)\">\n**What changes:** nothing.\n\n**What depends on it:** staging is created from the new schema.sql. The crawler dist, once rebuilt, writes `language` to staging. The updater restarts the Engine after the merge. If prod whitelist.db is not migrated by then, the restarted Engine serves broken `/api/video`.\n\n**Regression risk: low (code), medium (process).**\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"parse_tags / build_text (lines 19-54), queries (187-205)\">\n**What changes:** nothing. It reads `tags_json` and `category` by name, and not `language`.\n\n**Regression risk: none.** `\"[]\"` parses to no tags. Embeddings are not recomputed on refresh; that is the plan's accepted staleness.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"FTS lexical query / row projection (lines 60-70)\">\n**What changes:** nothing. It uses explicit columns.\n\n**Regression risk: none.** It reflects refreshed tags and category through the triggers.\n</impact>\n<impact path=\"engine/server/db/jobs/repair-video-channel-names.py\" element=\"lazy load of sync-whitelist.py\">\n**What changes:** nothing.\n\n**What depends on it:** it loads `sync-whitelist.py`, which parses schema.sql at import. Its UPDATE touches only `channel_name`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"create_table_and_indexes_from_source / copy_and_prune_prod (lines 198-340)\">\n**What changes:** nothing. It copies the table DDL from the source DB and then runs `INSERT ... SELECT *`, so the shapes always match.\n\n**Regression risk: low.** If the source prod is unmigrated, the mini-prod lacks `language`, and the merge silently drops it (see the merge entry).\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"hand-written CREATE TABLE videos (line 157)\">\n**What changes:** nothing. It never calls `fetch_video_row` or the sync schema checks.\n\n**Regression risk: none.** Listed so nobody \"fixes\" it.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture on WHITELIST_DB (lines 34, 105-145); sys.path with client/backend first (37-43)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- **Engine fixture.** The session Engine runs on the worktree's `engine/server/db/whitelist.db`, which is shared with main. No `tests/active` file calls `/api/video` (grep), so the suite stays green on an unmigrated DB, but a manual or smoke run does not.\n- **Imports in the new handler test.** `handlers.video` does `from http_utils import respond_json`. `client/backend` holds only `server.py` and `lib/`, so a top-level `http_utils` resolves to `engine/server/api/http_utils.py` once that is on `sys.path`. `server` is already cached as the Client module, and `video.py` does not import `server`.\n\n**Regression risk: low.** Do not make the Engine migrate the DB at startup (plan decision): that would ALTER the shared DB from a worktree run.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_video_proxy check (line 582)\">\n**What changes:** nothing.\n\n**What depends on it:** it expects `/api/video` to answer 200 through the Client on the live whitelist.db.\n\n**Regression risk: medium.** It fails until `migrate-whitelist.py` has run on that DB. `tests/run-installers-smoke.sh:647` has the same check, with `|| true`, so it only reports.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"stages crawl:videos:tags (215) \u2192 sync-whitelist (227-228)\">\n**What changes:** nothing.\n\n**What depends on it:** the tags stage opens crawl.db through `VideoStore`, so the additive crawler migration runs automatically. The sync stage then fails on an unmigrated existing whitelist.db.\n\n**Regression risk: medium (operational).** The runbook, or the script, needs a `migrate-whitelist.py` step before sync. Adding it to the script is outside the plan; document it.\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"player-info block between video-meta-row (68-95) and video-description (96)\">\n**What changes:** a new `video-taxonomy` block with category and language spans and a tags container.\n\n**What depends on it:** `index.ts` looks the elements up by id at module top (lines 22-48 pattern).\n\n**Constraints:**\n- The CSP (line 8) has `style-src 'self'`, so there are no inline `style=` attributes. Hide elements with the `hidden` attribute or a class.\n- Use a semantic list or `role` for the chips, and an `aria-label` for the tags region.\n\n**Regression risk: low.**\n- Issue 14 (collapsible description) edits the adjacent `video-description` markup, CSS and fill code, so a merge conflict is likely if both are open.\n- `client/frontend/dist/video-page.html` is the built copy (see the dist entry).\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"VideoMetadata type (481-501), fetchVideoMetadataFromServer (517-555), fetchVideoMetadataFromInstance (560-625), loadVideo (85-229), element lookups (22-48)\">\n**What changes:**\n- `VideoMetadata` gains `tags`, `category` and `language`.\n- The server path reads `data.tags` (array filtered to strings), `data.category` and `data.language`, with `\"\"` or `[]` defaults.\n- The instance path reads `data.tags`, `(data.category as {label}).label` and `(data.language as {label}).label`, with type guards because the payload is `Record<string, unknown>`.\n- `loadVideo` renders with `textContent` and `createElement` / `replaceChildren` for the chips.\n\n**Details to get right:**\n- **Null metadata.** When both fetches fail, `metadata` is `null`. The block should then be hidden, or show \"No tags\", consistently. Decide which.\n- **\"Unknown\" asymmetry.** For an unset language, PeerTube sends `{id: null, label: \"Unknown\"}`. The server path hides it: the stored value is NULL, which becomes `\"\"`. The instance fallback shows \"Unknown\" through `language.label`, so the two paths disagree. Treat a null `id` as empty on the instance path too, or accept the difference and document it.\n- **Category \"Unknown\".** It shows on both paths.\n- **Existing HTML interpolation.** Existing rendering uses `innerHTML` with `escapeHtml` elsewhere. The new code must not interpolate tags into `innerHTML`.\n\n**Regression risk: low.** `fetchVideoMetadataFromServer` returns null on `!response.ok`, which already covers the 502 case.\n</impact>\n<impact path=\"client/frontend/src/video.css\" element=\"new .video-taxonomy / chip styles near .video-meta-row (309-347) and .metric (325-332)\">\n**What changes:** compact label and chip rules that reuse `--line`, `--muted`, `--accent-strong`, the `rgba(180, 87, 55, 0.08)` background, `border-radius: 999px` and 0.8\u20130.9rem font sizes.\n\n**Gotcha:** an author `display:` rule overrides the UA `[hidden]{display:none}`. `.instance-meta` (`display: inline-flex`) already has this latent bug. If the new spans get `display: inline-flex` or `flex`, add an explicit `.video-taxonomy [hidden] { display: none; }` or equivalent, or `hidden = true` will not hide them. The existing `:empty` pattern (lines 304-307) is an alternative.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/dist\" element=\"committed build output: video-page.html, assets/video-*.js, assets/video-*.css\">\n**What changes:** a rebuild with `vite build` (`npm run build`). The hashed asset names change, `dist/video-page.html` references the new names, and the old `video-gjYm1MC8.js` and `video-ypOuFwNw.css` become orphans to delete. Shared chunks may be re-hashed too.\n\n**What depends on it:** production serving. DEPLOYMENT.md:301 says to re-run the rsync after every build.\n\n**Regression risk: low.** Commit a consistent set. No `tests/active` test reads the dist; the frontend tests bundle `src` with esbuild.\n</impact>\n<impact path=\"tests/active/test_video_handler.py\" element=\"new test module (handler, labels, migration)\">\n**What changes:** a new file.\n\n**Imports:**\n- It loads `sync-whitelist.py` through `importlib.util.spec_from_file_location`, under a unique module name. `test_repair_video_channel_names.py` uses `sync_whitelist_channel_names` and `test_host_normalisation` uses `sync_whitelist_job`.\n- It inserts `engine/server` and `engine/server/api` into `sys.path` and does `from handlers import video`. This works in-process, as `test_internal_events.py:37` does: `video.py` imports no numpy or faiss (`data.time`, `data.popularity`, `http_utils`).\n\n**Fixture DB:**\n- A `tmp_path` DB with `ensure_whitelist_schema` + `ensure_content_schema`, and `row_factory = sqlite3.Row`, so that `dict(row)` works.\n- `videos` needs `last_checked_at` (NOT NULL). `instances` needs `last_error`, `last_error_at` and `last_error_source` set to non-NULL for the failure assertions.\n- A `channels` row with a matching `channel_id`.\n\n**Stand-in server:** `db`, `db_lock` (`threading.Lock`), `video_error_threshold` and `popularity_like_weight`.\n\n**Monkeypatch targets:** `video.respond_json`, `video.fetch_instance_json` (path-keyed), and `video.urlopen` for the parse-guard cases. The fake response must support `with`, `.status` and `.read()`.\n\n**Assertions:**\n- Whole-row `SELECT *` snapshots before and after, for failure.\n- `last_checked_at` is strictly greater than a seeded old value. Seed it well in the past, not with `now_ms()`, to avoid equal-millisecond flakes.\n\n**Regression risk: low for production, medium for suite stability.**\n- It must never use the `engine`/`dataset` fixtures or `WHITELIST_DB`.\n- A `urlopen` fake that raises `URLError` checks the kept network contract.\n- A `channel` in the payload triggers a second `fetch_instance_json` call, so the path-keyed fake must answer `/api/v1/video-channels/...` or return `None`.\n</impact>\n<impact path=\"tests/active/test_videos_worker.py\" element=\"test_crawl_writes_each_hosts_own_channel_name and a new additive-migration case\">\n**What changes:**\n- The alpha payload items gain `language: {id: \"en\", label: \"English\"}`, and the SELECT and assertion include `language`.\n- A second case pre-creates crawl.db with the old videos DDL. It has to be written inline, because schema.sql will already contain `language`. It then runs `crawlVideos` and asserts the column exists and is filled.\n\n**What depends on it:**\n- node on PATH, `engine/crawler/node_modules` (better-sqlite3) and a fresh dist.\n- The `_dist_is_stale` gate covers only the `videos-worker` pair.\n- The test builds its DB with `conn.executescript(SCHEMA...)`, so the new-schema case never exercises the ALTER. The second case is the one that proves the migration.\n\n**Regression risk: medium.** The node, dist and node_modules requirements are hard, and missing ones fail rather than skip. Keep one test per claim, and keep the module docstring bullets in the file's style.\n</impact>\n<impact path=\"tests/active/test_repair_video_channel_names.py\" element=\"crawl/whitelist fixtures built from schema.sql and ensure_content_schema\">\n**What changes:** nothing. The inserts name their columns, and the new nullable column is harmless.\n\n**What depends on it:** it is the precedent for the `_load_job` loader the new test copies.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"dist staleness gate for host-filters (_dist_is_stale)\">\n**What changes:** nothing.\n\n**Regression risk: low.** `npm run build` rewrites every dist file. If `host-filters.js` changes, commit it; by commit time it is then newer, not stale.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (lines 133-139)\">\n**What changes:** at harvest:\n- Map `test_video_handler.py` to `engine/server/api/handlers/video.py`, `engine/server/data/peertube_labels.py`, `engine/server/db/jobs/whitelist_migrations.py` and `engine/server/db/jobs/sync-whitelist.py`.\n- Extend `test_videos_worker.py`'s entry with `engine/crawler/src/db.ts`, `engine/crawler/dist/db.js` and `engine/crawler/schema.sql`. Today it lists only the videos-worker pair, so a `db.ts`-only change would not re-run it.\n\n**Regression risk: low.** The file is local and gitignored.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked test record (and tests/last_test_output.txt)\">\n**What changes:** both are regenerated by `validate_tests.py`.\n\n**Regression risk: none functionally.** They conflict on merge: take main's copy and re-run with `--compare`.\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n\n<doc path=\"DATA_BUILD.md\">\nSections 1 and 2:\n- Add a note that the crawler adds `videos.language` (the PeerTube language code) to an existing `crawl.db` the first time any crawler command opens it.\n- Add a note that `sync-whitelist.py` refuses a `crawl.db` the crawler has not opened yet (superset check).\n- Add a note that `sync-whitelist.py` refuses an existing `whitelist.db` until `migrate-whitelist.py` has added the column.\n- Beside the existing `migrate-whitelist.py` block (lines 155-158), add the upgrade order: merge; open or run the crawler once on `crawl.db`; run `migrate-whitelist.py` on every `whitelist.db`, prod included; then restart the Engine.\n\nTwo notes for step 2:\n- `run-dataset-build.sh` does not migrate on its own.\n- Refreshes made by `/api/video` in `whitelist.db` are replaced by the next sync.\n</doc>\n<doc path=\"engine/server/README.md\">\nLine 9 (`/api/video`) should describe:\n- **Refresh.** One source fetch refreshes and persists title, description, stats, tags, category, language, nsfw, duration and thumbnail.\n- **Failure.** A failed or malformed source leaves the DB untouched and answers from the DB.\n- **Response keys.** The new keys are `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Category and language are mapped to PeerTube default labels.\n- **Migration.** The whitelist DB must be migrated (`language` column).\n</doc>\n<doc path=\"DEPLOYMENT.md\">\n**Line 374:** optionally note that `/api/video` writes back to `whitelist.db` only when the source answers inside the request's statement budget.\n\n**Upgrade notes:** add a short note, or a Triage row, for this deploy:\n- Before restarting the Engine, run `migrate-whitelist.py` on the Engine's `whitelist.db`.\n- Symptom when it is skipped: every video page falls back to direct-instance metadata. The Client proxy logs 502 `ENGINE_PROXY_UNAVAILABLE` on `/api/video`, and the Engine journal shows `no such column: v.language`.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nImplementation-order step 2 (line 142) refers to feed-panel I1 language capture.\n- This build already captures `videos.language` (the code), so I1 is partly delivered under a different column name than plan 04 proposes.\n- Update the step so it names what remains: label storage if needed, backfill I3, and the filter I2.\n- Note that existing rows get a language only from a full re-crawl or from video-page views.\n</doc>\n<doc path=\"docs/project/plans/archive/04-feed-parameter-panel.md\">\nI1 (lines 19-20, 47-48) specifies `language_id` + `language_label`. Record, or link from the roadmap, that `language` (code only) now exists and that labels resolve at read time through `engine/server/data/peertube_labels.py`, so that I1 does not add a duplicate column.\n</doc>\n<doc path=\"docs/project/plans/18-english-subtitles.md\">\nLines 20, 43 and 90 say the `videos` table stores no language and that there is \"no language column to select by\". After this build both statements are false. Update them, noting that coverage is sparse for existing rows.\n</doc>\n<doc path=\"docs/project/issues/10-video-metadata-completeness.md\">\nAt harvest on main, not in this worktree:\n- Set `Status: enhancement, complete` and append a delivery comment.\n- Record the accepted limits: default-only labels; \"Unknown\" category; removals of language and description are not propagated; persistence is best-effort under the 5 s statement deadline; refreshes are lost at the next sync.\n- Move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/issues/14-collapsible-description.md\">\nNo content change is needed. Note at harvest that the video page now has a taxonomy block between `video-meta-row` and `video-description`. Issue 14 edits the adjacent markup, CSS and fill code, so expect a merge conflict.\n</doc>\n\n</docs_checklist>\n\n<highest_risk>\n\nengine/server/api/handlers/video.py fetch_video_row(): once it selects `v.language`, every unmigrated whitelist.db (prod, dev, and the one the worktrees share) raises `no such column`. `similar.py` re-raises that error, so the Engine drops the connection on every `/api/video`, and the Client proxy answers 502. The page falls back to instance-direct silently, and both smoke scripts fail. The only guard is the manual `migrate-whitelist.py` step before the Engine restarts, and `run-dataset-build.sh` / `sync-whitelist.py` also refuse to run until it is done.\nengine/server/api/handlers/video.py handle_video_request / fetch_instance_video_dynamic: the single success signal must be tested as `dynamic is None`. Every `\"\"` value must be mapped to None before the merge, or `\"\"` overwrites stored data despite R2: this covers `resolve_asset_url`'s `\"\"` thumbnail and `extract_category`'s plain `\"\"`. Separately, the whole write runs inside the request's 5 s statement deadline after up to 16 s of outbound fetches, so slow sources answer 200 with fresh values but never persist. The stubbed tests cannot show this.\nengine/crawler/src/db.ts upsert and additive migration, and dist/db.js: the 26-slot positional INSERT, VALUES and `run()` lists must stay aligned, and the ALTER must run after `migrateVideos` and before the second schema exec. `language = excluded.language` lets a re-crawl wipe a language to NULL. `test_videos_worker.py`'s staleness gate checks only `videos-worker.js`, so an unrebuilt `db.js` ships silently. It would surface only as a missing language, or as a `sync-whitelist` superset failure on production crawl.db.\n\n</highest_risk>",
    "step_4_reassess": "<summary>\nI opened the files the inventory cites and checked its claims against them: `video.py`, `similar.py`, `data/db.py`, `whitelist_migrations.py`, `migrate-whitelist.py`, `sync-whitelist.py`, the crawler's `db.ts` and `videos-worker.ts`, `merge-staging-db.py`, `test-orchestrator-smoke.py`, `test_videos_worker.py`, `conftest.py` and the video page `index.ts`. Every entry I checked holds. The plan works as designed. Its risk is operational (migration order), not a design flaw. Nothing in the tree contradicts the requirements or the settled plan, and I found no impact the inventory does not already carry.\n<question id=\"1\">\nYes. Today `fetch_instance_video_dynamic` turns a failed detail fetch into `{}` via `or {}` (video.py:164). The write block runs whenever that dict is truthy (line 293), so the missing single success signal is exactly where the plan puts it. Returning `None` and testing `dynamic is None` restores it, and the merge at lines 229-258 already uses the \"None keeps DB\" pattern the plan extends. Three implementation details, all already in the inventory, decide whether R2 holds in practice:\n- `thumbnail_url` must map `resolve_asset_url`'s `\"\"` to `None` (lines 92-93).\n- `extract_category` must pass plain strings through `pick_text`, because line 145 returns `\"\"` as-is.\n- `channel` needs an `isinstance(dict)` guard.\n\nThe crawler side works too:\n- The upsert has exactly 25 `?` plus `NULL, NULL, 0` (db.ts:1168).\n- `applyBaseSchema` runs `schemaSql`, the migrations, then `schemaSql` again (lines 65-71), so the additive step fits between `migrateVideos` and the second exec.\n- The sync column lists come from schema.sql (`VIDEO_COLUMNS`, line 96), so the copy picks `language` up without edits.\n\nThe test design is sound:\n- `http_utils` resolves only to `engine/server/api/http_utils.py`, because the client copy lives under `lib/`.\n- `data/__init__.py` and `data/popularity.py` import nothing heavy.\n- The name `peertube_labels` does not collide with anything, and no label map exists anywhere yet.\n</question>\n<question id=\"2\">\n- **Deployment coupling.** The new `v.language` in `fetch_video_row` raises `OperationalError`. It is not \"interrupted\", so `do_GET` re-raises it (similar.py:438-440) and every `/api/video` drops its connection until `migrate-whitelist.py` has run. `sync-whitelist.py` refuses to run through the exact and superset checks (lines 186-216), and `run-dataset-build.sh` fails at sync.\n- **Refreshes are short-lived.** `rebuild_content_tables` reloads `videos` from crawl.db on every sync, so a refresh lasts only until the next dataset build.\n- **Slow sources are never persisted.** The 5 s `statement_deadline` is armed before the handler runs (similar.py:436), so a source slower than that is fetched but not saved.\n- **Crawler and Engine disagree on unset language.** The crawler's `language = excluded.language` overwrites with NULL, while the Engine's \"null keeps DB\" rule does not.\n- **Failures stop writing.** Failed refreshes no longer bump `last_checked_at`, clear `instances.last_error*`, or null `channels.channel_name`. Grep finds nothing that relies on those side effects.\n</question>\n<question id=\"3\">\nBefore the new Engine serves, `migrate-whitelist.py` must run against every whitelist.db, and the crawler must open crawl.db once. The runbook and `run-dataset-build.sh` need that step before sync.\n\nBoth dists must be rebuilt and committed:\n- **Crawler dist:** `db.js` too. The staleness gate at test_videos_worker.py:38 checks only the videos-worker pair.\n- **Client dist:** orphaned hashed assets are removed.\n\nTwo things stay unchanged:\n- The migration test's legacy fixture keeps the error columns. Otherwise `migrate_videos_schema` takes its destructive rebuild path, which drops `videos_fts` and `video_embeddings` (whitelist_migrations.py:262-266).\n- The Engine does not migrate at startup, because the conftest Engine runs on the shared `WHITELIST_DB` (conftest.py:34).\n</question>\n<question id=\"4\">\n- **Failure path.** A failed or malformed source used to still write the row and clear instance errors. Now it writes nothing and returns the DB values. A malformed body used to drop the connection (the proxy then answered 502, and the page fell back to fetching from the instance directly); now it returns a 200 built from the DB.\n- **Refresh scope.** A successful refresh now also writes `language`, `duration` and `thumbnail_url`.\n- **Empty tags.** An empty tag list is stored as `\"[]\"` instead of being skipped.\n- **Category values.** A category object with no label now stores its id as a string.\n- **Response.** It gains `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Every existing key is kept.\n- **Page.** The video page shows category, language and tag chips.\n- **Schemas.** crawl.db and whitelist.db each gain a nullable `language` column.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Write the three R2 guards the inventory found into the phase plan as explicit tasks, each with a test case: `thumbnail_url` `\"\"`\u2192`None`, `extract_category` plain strings through `pick_text` (with a `bool` guard on numbers), and an `isinstance(dict)` guard on `channel`. Cost: about three lines of handler code and three small test cases. Without them, a partial payload can blank a stored thumbnail or category, which violates R2.\n2. Add a `migrate-whitelist.py` step to `scripts/run-dataset-build.sh` before the sync stage, not only to the runbook. Cost: one script line, and it adds a file outside the plan's four parts, so it needs your approval. The step backs up by default (a full copy of a large DB) unless it is passed `--no-backup`. If you decline, the first dataset build after merge fails at the exact column check until someone runs the migration by hand.\n3. Choose one fix for the \"Unknown\" language mismatch: on the instance-direct fallback, treat a null `language.id` as empty, so the server path and the fallback both hide an unset language. Cost: one guard in `fetchVideoMetadataFromInstance`. The alternative costs nothing but a line in the harvest notes explaining why the two paths show different things.\n4. Decide on `json.dumps(..., ensure_ascii=False)` for refreshed tags, to match the crawler's raw UTF-8 so FTS indexes words rather than `\\u` escapes. Cost: one argument. This is a behaviour change beyond the requirements, so leave it out unless you want it.\n5. Fix the \"500\" wording in the plan's gotchas when harvest notes are written. An unmigrated DB or an uncaught fetch error drops the connection, and the Client proxy answers 502. It is a documentation-only fix and changes nothing in the build.\n6. At harvest, map `test_video_handler.py` and extend the `test_videos_worker.py` entry in `.un/skills/devsecops/config.json` to cover `db.ts`, `dist/db.js` and `schema.sql`. Cost: a local config edit. Without it, a change only to `db.ts` never re-runs the worker test.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n\n# Draft implementation: issue 10, video metadata completeness\n\nI read every file this touches before drafting: `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, `schema.sql`, `db.ts`, `videos-worker.ts`, `video-page.html`, `index.ts`, `video.css`, `test_videos_worker.py`, `test_repair_video_channel_names.py` and `test_internal_events.py`. New code copies each file's own style: one-line docstrings or `/** Handle \u2026 */` blocks, the `has_x`/`x_expr` rebuild pattern, `pick_*` helpers, and bulleted test-module docstrings.\n\nThe step's ladder placeholder (`{rat_tail_ladder}`) arrived unrendered. This draft is therefore written against R1\u2013R7, the plan and the settled impact inventory.\n\n## What has to be testable (ladder rung 1)\n\n| Claim | Where it is proven |\n|---|---|\n| Success writes all R2 fields, bumps `last_checked_at`, resets `instances.last_error*`, and returns the R5 keys | `test_video_handler.py::test_success_refreshes_row_and_response` |\n| A caught network error (stub `None`, and real `urlopen` raising `URLError`) writes nothing and answers from the DB | `test_fetch_failure_leaves_db_untouched[stub-none, urlopen-urlerror]` |\n| A malformed body (not JSON, bad UTF-8, a JSON list) writes nothing | `test_fetch_failure_leaves_db_untouched[not-json, bad-utf8, json-list]` |\n| A partial payload keeps the stored tags and category | `test_partial_payload_keeps_tags_and_category` |\n| `tags: []` stores `\"[]\"` and returns `[]` | `test_empty_tag_list_propagates` |\n| A source change between two requests is reflected in the DB and the response | `test_second_request_reflects_source_change` |\n| Labels: `\"15\"` gives the label, an unknown id stays raw, a text category passes through, a language code gives its label, an unknown code stays raw | `test_response_labels` (parametrised, DB-only path) |\n| The whitelist migration adds `language`, keeps rows and FTS triggers, and is idempotent | `test_migration_adds_language_column` |\n| The crawler persists `language` | `test_videos_worker.py::test_crawl_writes_each_hosts_own_channel_name` (extended) |\n| The crawler adds `language` to an old crawl.db | `test_videos_worker.py::test_crawl_adds_language_to_existing_db` |\n\n## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/handlers/video.py` | Parse guard, `None` success signal, new extractors, one merge, a write only on success, new response keys |\n| `engine/server/data/peertube_labels.py` | **new**: `CATEGORY_LABELS`, `LANGUAGE_LABELS`, `category_label`, `language_label` |\n| `engine/server/db/jobs/whitelist_migrations.py` | `migrate_videos_language`; the rebuild carries `language` |\n| `engine/server/db/jobs/sync-whitelist.py` | `language TEXT` in `ensure_content_schema` |\n| `engine/crawler/schema.sql` | `language TEXT` after `category` (no index) |\n| `engine/crawler/src/db.ts` | `migrateVideosLanguage`; the rebuild carries `language`; `VideoUpsertRow.language`; the upsert |\n| `engine/crawler/src/videos-worker.ts` | `PeerTubeLanguage`, `extractLanguage`, `toVideoRow.language` |\n| `engine/crawler/dist/*.js` | `npm run build`, commit every changed dist file |\n| `client/frontend/video-page.html` | `video-taxonomy` block |\n| `client/frontend/src/pages/video-page/index.ts` | Type, both fetch paths, `renderTaxonomy` |\n| `client/frontend/src/video.css` | Taxonomy and chip styles |\n| `client/frontend/dist` | `npm run build`; delete orphaned hashed assets |\n| `tests/active/test_video_handler.py` | **new** |\n| `tests/active/test_videos_worker.py` | Extended, plus one new case |\n\nUnchanged on purpose: `client/backend/server.py` (it passes the body through), `similar.py`, `updater-worker.py`, `merge-staging-db.py` and `build-video-embeddings.py`.\n\n---\n\n## 1. `engine/server/api/handlers/video.py`\n\n### Imports\n```python\nfrom data.time import now_ms\nfrom data.popularity import compute_popularity\nfrom data.peertube_labels import category_label, language_label\nfrom http_utils import respond_json\n```\n\n### `fetch_video_row`\nThe SELECT list gains three lines after `v.nsfw`:\n```sql\n          v.nsfw,\n          v.language,\n          v.duration,\n          v.thumbnail_url,\n          v.last_checked_at,\n```\n\n### `fetch_instance_json`\nInvariant: it returns a `dict`, or `None`. It never raises for network, HTTP, decode or parse failures. The `# pragma: no cover` comes off because the tests now cover this branch.\n```python\ndef fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:\n    \"\"\"Fetch a JSON object from a PeerTube instance API path; None on network failure, non-200, a malformed body or a non-object body.\"\"\"\n    url = f\"https://{host}{path}\"\n    req = Request(url, headers={\"accept\": \"application/json\"})\n    try:\n        with urlopen(req, timeout=8) as resp:\n            if resp.status != 200:\n                return None\n            data = json.loads(resp.read().decode(\"utf-8\"))\n    except (HTTPError, URLError, TimeoutError) as exc:\n        logging.info(\"[video] instance request failed: %s\", exc)\n        return None\n    except ValueError as exc:\n        # UnicodeDecodeError and JSONDecodeError are both ValueError.\n        logging.info(\"[video] instance response is not valid JSON: host=%s path=%s: %s\", host, path, exc)\n        return None\n    if not isinstance(data, dict):\n        logging.info(\"[video] instance response is not a JSON object: host=%s path=%s\", host, path)\n        return None\n    return data\n```\n\n### New and changed helpers (placed next to the existing ones)\n```python\ndef pick_present(value: Any, fallback: Any) -> Any:\n    \"\"\"Return value unless it is None, else fallback (source-over-DB merge rule).\"\"\"\n    return fallback if value is None else value\n\n\ndef id_text(value: Any) -> str | None:\n    \"\"\"Normalize a PeerTube id to text: a non-empty trimmed string or an int (never a bool); None otherwise.\"\"\"\n    if isinstance(value, bool):\n        return None\n    if isinstance(value, int):\n        return str(value)\n    return pick_text(value)\n\n\ndef to_tags_json(value: Any) -> str | None:\n    \"\"\"Convert a tag list to a JSON array of its string elements (\"[]\" when there are none); None when the value is not a list.\"\"\"\n    if isinstance(value, list):\n        return json.dumps([tag for tag in value if isinstance(tag, str)], ensure_ascii=False)\n    return None\n\n\ndef extract_category(value: Any) -> str | None:\n    \"\"\"Extract the category label/name, else its id as text; a plain string or int is kept as text; None when absent or empty.\"\"\"\n    if isinstance(value, dict):\n        return pick_text(value.get(\"label\"), value.get(\"name\")) or id_text(value.get(\"id\"))\n    return id_text(value)\n\n\ndef extract_language(value: Any) -> str | None:\n    \"\"\"Extract the PeerTube language code: an object's id or a plain non-empty string; None for a null id or anything else.\"\"\"\n    if isinstance(value, dict):\n        return pick_text(value.get(\"id\"))\n    return pick_text(value)\n\n\ndef tags_from_json(value: Any) -> list[str]:\n    \"\"\"Parse stored tags_json into its string tags; [] when null, empty, invalid or not a list.\"\"\"\n    if not isinstance(value, str) or not value:\n        return []\n    try:\n        parsed = json.loads(value)\n    except ValueError:\n        return []\n    if not isinstance(parsed, list):\n        return []\n    return [tag for tag in parsed if isinstance(tag, str)]\n```\n\nDecisions:\n- **`ensure_ascii=False`.** Refreshed tags are stored as raw UTF-8, the same as the crawler's `JSON.stringify`, so FTS indexes the words rather than `\\uXXXX` escapes. This resolves the judgment call the `to_tags_json` inventory entry left open.\n- **`extract_category` with a plain string.** It now goes through `pick_text`, so `\"\"` or whitespace keeps the DB value (the gap the inventory found).\n- **Integer ids only.** Floats and bools are rejected; PeerTube category ids are integers.\n\n### `fetch_instance_video_dynamic`\nInvariant: `None` exactly when the detail fetch gave no dict (R1). Otherwise a dict in which `None` always means \"keep the DB value\".\n```python\ndef fetch_instance_video_dynamic(host: str, video_id: str) -> dict[str, Any] | None:\n    \"\"\"Fetch live video metadata from instance and normalize fields; None when the video detail fetch fails (the single success signal).\"\"\"\n    detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\")\n    if detail is None:\n        return None\n    account = detail.get(\"account\")\n    if not isinstance(account, dict):\n        account = {}\n    channel = detail.get(\"channel\")\n    if not isinstance(channel, dict):\n        channel = {}\n    channel_slug = pick_text(channel.get(\"name\"))\n    # ... channel_display / channel_followers / channel_detail block unchanged ...\n    return {\n        \"title\": pick_text(detail.get(\"name\"), detail.get(\"title\")),\n        \"description\": pick_text(detail.get(\"description\")),\n        \"views\": ...,  # unchanged\n        \"likes\": ...,  # unchanged\n        \"dislikes\": ...,  # unchanged\n        \"tags_json\": to_tags_json(detail.get(\"tags\")),\n        \"category\": extract_category(detail.get(\"category\")),\n        \"language\": extract_language(detail.get(\"language\")),\n        \"nsfw\": to_nullable_bool(detail.get(\"nsfw\")),\n        \"duration\": pick_number(detail.get(\"duration\")),\n        \"thumbnail_url\": resolve_asset_url(host, pick_text(detail.get(\"thumbnailUrl\"), detail.get(\"thumbnailPath\"))) or None,\n        # channel_slug, channel_display, channel_followers, account_* unchanged\n    }\n```\nThe `or None` on `thumbnail_url` is there because `resolve_asset_url` returns `\"\"` for a missing value. Without it, a missing thumbnail would overwrite the stored one with `\"\"`.\n\n### `handle_video_request`: merge, response, write\n```python\n    instance_domain = row.get(\"instance_domain\") or host_param or \"\"\n    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else None\n    # One merged value set feeds both the response and the UPDATE; on failure `source` is empty, so every field is the DB value.\n    source = dynamic if dynamic is not None else {}\n\n    title = source.get(\"title\") or row.get(\"title\")\n    description = source.get(\"description\") or row.get(\"description\")\n    views = pick_present(source.get(\"views\"), row.get(\"views\"))\n    likes = pick_present(source.get(\"likes\"), row.get(\"likes\"))\n    dislikes = pick_present(source.get(\"dislikes\"), row.get(\"dislikes\"))\n    channel_display = source.get(\"channel_display\") or row.get(\"channel_display_name\") or row.get(\"channel_name\")\n    channel_slug = source.get(\"channel_slug\") or row.get(\"channel_slug\")\n    channel_followers = pick_present(source.get(\"channel_followers\"), row.get(\"channel_followers_count\"))\n    tags_json = pick_present(source.get(\"tags_json\"), row.get(\"tags_json\"))\n    category = pick_present(source.get(\"category\"), row.get(\"category\"))\n    language = pick_present(source.get(\"language\"), row.get(\"language\"))\n    nsfw = pick_present(source.get(\"nsfw\"), row.get(\"nsfw\"))\n    duration = pick_present(source.get(\"duration\"), row.get(\"duration\"))\n    thumbnail_url = pick_present(source.get(\"thumbnail_url\"), row.get(\"thumbnail_url\"))\n```\nThe `channel_url`, `embed_url` and `original_url` code is unchanged.\n\nThe response keeps all 18 keys; `\"accountAvatarUrl\": source.get(\"account_avatar_url\") or \"\"` replaces `dynamic.get(...)`. Six keys are appended:\n```python\n        \"tags\": tags_from_json(tags_json),\n        \"category\": category_label(category),\n        \"language\": language_label(language),\n        \"nsfw\": None if nsfw is None else bool(nsfw),\n        \"duration\": pick_number(duration),\n        \"thumbnailUrl\": thumbnail_url or \"\",\n```\n\nWrite block: the guard becomes `if dynamic is not None and instance_domain and row.get(\"video_id\"):` and it tests identity, not truthiness. The UPDATE becomes:\n```sql\nUPDATE videos\nSET title = ?, description = ?, channel_name = ?, views = ?, likes = ?, dislikes = ?,\n    popularity = ?,\n    tags_json = ?, category = ?, language = ?, nsfw = ?, duration = ?, thumbnail_url = ?, last_checked_at = ?\nWHERE video_id = ? AND instance_domain = ?\n```\nThe parameter tuple is extended in the same order: `\u2026, tags_json, category, language, nsfw, duration, thumbnail_url, checked_at, video_id, instance_domain`. The `channels` UPDATE, the `instances` reset, the transaction and the `OperationalError` catch are unchanged.\n\nInvariant: on failure no statement runs, so `last_checked_at`, `channels` and `instances.last_error*` stay exactly as they were.\n\nPre-existing issue, flagged and not changed: on success with no channel slug anywhere, the `channels` UPDATE writes `channel_name = NULL`.\n\n---\n\n## 2. `engine/server/data/peertube_labels.py` (new)\n```python\n\"\"\"PeerTube default video category and language labels.\n\nResponsibilities:\n- Map PeerTube's stock category ids and language codes to display labels for /api/video.\n- Leave unknown ids and codes raw (named simplification: plugin-added or renamed entries are not covered; upgrade path is caching each instance's /api/v1/videos/categories and /api/v1/videos/languages).\n\"\"\"\nfrom __future__ import annotations\n\nCATEGORY_LABELS: dict[str, str] = {\n    \"1\": \"Music\", \"2\": \"Films\", \"3\": \"Vehicles\", \"4\": \"Art\", \"5\": \"Sports\", \"6\": \"Travels\", \"7\": \"Gaming\", \"8\": \"People\", \"9\": \"Comedy\",\n    \"10\": \"Entertainment\", \"11\": \"News & Politics\", \"12\": \"How To\", \"13\": \"Education\", \"14\": \"Activism\", \"15\": \"Science & Technology\", \"16\": \"Animals\", \"17\": \"Kids\", \"18\": \"Food\",\n}\n\nLANGUAGE_LABELS: dict[str, str] = { ... }  # see below\n\n\ndef category_label(value: str | None) -> str:\n    \"\"\"Return the display label for a stored category: a digit-only id resolves through the default map, anything else (or an unknown id) is returned as is; \"\" when empty.\"\"\"\n    if not isinstance(value, str) or not value:\n        return \"\"\n    if value.isascii() and value.isdigit():\n        return CATEGORY_LABELS.get(value, value)\n    return value\n\n\ndef language_label(value: str | None) -> str:\n    \"\"\"Return the display label for a stored language code (case-sensitive); an unknown code is returned raw; \"\" when empty.\"\"\"\n    if not isinstance(value, str) or not value:\n        return \"\"\n    return LANGUAGE_LABELS.get(value, value)\n```\n\n**`LANGUAGE_LABELS` contents.** This is PeerTube's `buildLanguages()` output: living ISO 639-1 languages keyed by their 639-1 code, plus the extra 639-3 set, keyed by the 639-3 code, including the sign languages. The draft literal below was written from memory. Before commit, the implementation step **must replace it wholesale** with the JSON from a stock instance's `GET /api/v1/videos/languages`, pasted as a literal. This is the \"copied once\" step in the plan, and it removes the fidelity risk rather than accepting it.\n```python\nLANGUAGE_LABELS: dict[str, str] = {\n    \"aa\": \"Afar\", \"ab\": \"Abkhazian\", \"af\": \"Afrikaans\", \"ak\": \"Akan\", \"am\": \"Amharic\", \"an\": \"Aragonese\", \"ar\": \"Arabic\", \"as\": \"Assamese\", \"av\": \"Avaric\", \"ay\": \"Aymara\", \"az\": \"Azerbaijani\",\n    \"ba\": \"Bashkir\", \"be\": \"Belarusian\", \"bg\": \"Bulgarian\", \"bi\": \"Bislama\", \"bm\": \"Bambara\", \"bn\": \"Bengali\", \"bo\": \"Tibetan\", \"br\": \"Breton\", \"bs\": \"Bosnian\",\n    \"ca\": \"Catalan\", \"ce\": \"Chechen\", \"ch\": \"Chamorro\", \"co\": \"Corsican\", \"cr\": \"Cree\", \"cs\": \"Czech\", \"cv\": \"Chuvash\", \"cy\": \"Welsh\",\n    \"da\": \"Danish\", \"de\": \"German\", \"dv\": \"Dhivehi\", \"dz\": \"Dzongkha\", \"ee\": \"Ewe\", \"el\": \"Greek\", \"en\": \"English\", \"eo\": \"Esperanto\", \"es\": \"Spanish\", \"et\": \"Estonian\", \"eu\": \"Basque\",\n    \"fa\": \"Persian\", \"ff\": \"Fulah\", \"fi\": \"Finnish\", \"fj\": \"Fijian\", \"fo\": \"Faroese\", \"fr\": \"French\", \"fy\": \"Western Frisian\",\n    \"ga\": \"Irish\", \"gd\": \"Scottish Gaelic\", \"gl\": \"Galician\", \"gn\": \"Guarani\", \"gu\": \"Gujarati\", \"gv\": \"Manx\",\n    \"ha\": \"Hausa\", \"he\": \"Hebrew\", \"hi\": \"Hindi\", \"ho\": \"Hiri Motu\", \"hr\": \"Croatian\", \"ht\": \"Haitian\", \"hu\": \"Hungarian\", \"hy\": \"Armenian\", \"hz\": \"Herero\",\n    \"id\": \"Indonesian\", \"ig\": \"Igbo\", \"ii\": \"Sichuan Yi\", \"ik\": \"Inupiaq\", \"is\": \"Icelandic\", \"it\": \"Italian\", \"iu\": \"Inuktitut\",\n    \"ja\": \"Japanese\", \"jv\": \"Javanese\", \"ka\": \"Georgian\", \"kg\": \"Kongo\", \"ki\": \"Kikuyu\", \"kj\": \"Kuanyama\", \"kk\": \"Kazakh\", \"kl\": \"Kalaallisut\", \"km\": \"Central Khmer\", \"kn\": \"Kannada\", \"ko\": \"Korean\", \"kr\": \"Kanuri\", \"ks\": \"Kashmiri\", \"ku\": \"Kurdish\", \"kv\": \"Komi\", \"kw\": \"Cornish\", \"ky\": \"Kirghiz\",\n    \"la\": \"Latin\", \"lb\": \"Luxembourgish\", \"lg\": \"Ganda\", \"li\": \"Limburgan\", \"ln\": \"Lingala\", \"lo\": \"Lao\", \"lt\": \"Lithuanian\", \"lu\": \"Luba-Katanga\", \"lv\": \"Latvian\",\n    \"mg\": \"Malagasy\", \"mh\": \"Marshallese\", \"mi\": \"Maori\", \"mk\": \"Macedonian\", \"ml\": \"Malayalam\", \"mn\": \"Mongolian\", \"mr\": \"Marathi\", \"ms\": \"Malay\", \"mt\": \"Maltese\", \"my\": \"Burmese\",\n    \"na\": \"Nauru\", \"nb\": \"Norwegian Bokm\u00e5l\", \"nd\": \"North Ndebele\", \"ne\": \"Nepali\", \"ng\": \"Ndonga\", \"nl\": \"Dutch\", \"nn\": \"Norwegian Nynorsk\", \"no\": \"Norwegian\", \"nr\": \"South Ndebele\", \"nv\": \"Navajo\", \"ny\": \"Nyanja\",\n    \"oc\": \"Occitan\", \"oj\": \"Ojibwa\", \"om\": \"Oromo\", \"or\": \"Oriya\", \"os\": \"Ossetian\", \"pa\": \"Panjabi\", \"pl\": \"Polish\", \"ps\": \"Pushto\", \"pt\": \"Portuguese\", \"pt-PT\": \"Portuguese (Portugal)\", \"qu\": \"Quechua\",\n    \"rm\": \"Romansh\", \"rn\": \"Rundi\", \"ro\": \"Romanian\", \"ru\": \"Russian\", \"rw\": \"Kinyarwanda\",\n    \"sc\": \"Sardinian\", \"sd\": \"Sindhi\", \"se\": \"Northern Sami\", \"sg\": \"Sango\", \"si\": \"Sinhala\", \"sk\": \"Slovak\", \"sl\": \"Slovenian\", \"sm\": \"Samoan\", \"sn\": \"Shona\", \"so\": \"Somali\", \"sq\": \"Albanian\", \"sr\": \"Serbian\", \"ss\": \"Swati\", \"st\": \"Southern Sotho\", \"su\": \"Sundanese\", \"sv\": \"Swedish\", \"sw\": \"Swahili\",\n    \"ta\": \"Tamil\", \"te\": \"Telugu\", \"tg\": \"Tajik\", \"th\": \"Thai\", \"ti\": \"Tigrinya\", \"tk\": \"Turkmen\", \"tl\": \"Tagalog\", \"tn\": \"Tswana\", \"to\": \"Tonga\", \"tr\": \"Turkish\", \"ts\": \"Tsonga\", \"tt\": \"Tatar\", \"tw\": \"Twi\", \"ty\": \"Tahitian\",\n    \"ug\": \"Uighur\", \"uk\": \"Ukrainian\", \"ur\": \"Urdu\", \"uz\": \"Uzbek\", \"ve\": \"Venda\", \"vi\": \"Vietnamese\", \"wa\": \"Walloon\", \"wo\": \"Wolof\", \"xh\": \"Xhosa\", \"yi\": \"Yiddish\", \"yo\": \"Yoruba\", \"za\": \"Zhuang\",\n    \"zh\": \"Chinese\", \"zh-Hans\": \"Simplified Chinese\", \"zh-Hant\": \"Traditional Chinese\", \"zu\": \"Zulu\",\n    \"avk\": \"Kotava\", \"jbo\": \"Lojban\", \"kab\": \"Kabyle\", \"tlh\": \"Klingon\", \"tok\": \"Toki Pona\", \"zgh\": \"Standard Moroccan Tamazight\",\n    \"sgn\": \"Sign Languages\", \"ase\": \"American Sign Language\", \"asq\": \"Austrian Sign Language\", \"bfi\": \"British Sign Language\", \"bzs\": \"Brazilian Sign Language\", \"csl\": \"Chinese Sign Language\", \"cse\": \"Czech Sign Language\", \"dsl\": \"Danish Sign Language\", \"fsl\": \"French Sign Language\", \"gsg\": \"German Sign Language\", \"jsl\": \"Japanese Sign Language\", \"pks\": \"Pakistan Sign Language\", \"rsl\": \"Russian Sign Language\", \"sdl\": \"Saudi Arabian Sign Language\", \"sfb\": \"Langue des signes de Belgique Francophone\", \"sfs\": \"South African Sign Language\", \"ssp\": \"Spanish Sign Language\", \"swl\": \"Swedish Sign Language\", \"tsq\": \"Thai Sign Language\",\n}\n```\nThe tests assert only `\"en\"` gives \"English\" and `\"zh-Hans\"` gives \"Simplified Chinese\". The stock list keeps both, so pasting the real list will not break them.\n\n---\n\n## 3. Server whitelist DB\n\n### `whitelist_migrations.py`\n```python\ndef migrate_videos_language(conn: sqlite3.Connection) -> None:\n    \"\"\"Add the nullable `language` column (PeerTube language code) to a videos table that predates it.\n\n    Additive and idempotent: rows, `videos_fts` and its triggers are untouched, since none reference `language`.\n    \"\"\"\n    if not _table_exists(conn, \"videos\"):\n        return\n    if \"language\" in _columns(conn, \"videos\"):\n        return\n    conn.execute(\"ALTER TABLE videos ADD COLUMN language TEXT\")\n```\n\n`migrate_videos_schema` rebuild changes:\n- add `has_language = \"language\" in columns` and `language_expr = \"language\" if has_language else \"NULL\"`;\n- add `language TEXT,` after `category TEXT,` in `videos_new`;\n- add `language,` after `category,` in the INSERT list;\n- add `{language_expr},` after `category,` in the SELECT list.\n\nThe INSERT and SELECT lists stay positionally aligned.\n\n`migrate_whitelist_schema` then calls, in order:\n```python\n    migrate_instances_schema(conn, table_name)\n    migrate_channels_schema(conn)\n    migrate_videos_schema(conn)\n    migrate_videos_language(conn)\n```\n\n### `sync-whitelist.py`\nIn `ensure_content_schema`, add `language TEXT,` after `category TEXT,`. Nothing else: `VIDEO_COLUMNS` picks the column up from `schema.sql`.\n\n---\n\n## 4. Crawler\n\n### `schema.sql`\nAdd `  language TEXT,` after `  category TEXT,`. Do not add an index on it: the first `db.exec(schemaSql)` runs against old tables.\n\n### `db.ts`\n```ts\nfunction applyBaseSchema(db: Database.Database) {\n  db.exec(schemaSql);\n  migrateInstances(db);\n  migrateChannels(db);\n  migrateVideos(db);\n  migrateVideosLanguage(db);\n  db.exec(schemaSql);\n}\n\n/**\n * Add the videos.language column (PeerTube language code) to a crawl DB that predates it.\n */\nfunction migrateVideosLanguage(db: Database.Database) {\n  if (!tableExists(db, \"videos\")) return;\n  if (getColumns(db, \"videos\").includes(\"language\")) return;\n  db.exec(\"ALTER TABLE videos ADD COLUMN language TEXT\");\n}\n```\n\n`migrateVideos`:\n- add `const hasLanguage = columns.includes(\"language\");` and `const languageExpr = hasLanguage ? \"language\" : \"NULL\";`;\n- add `language TEXT,` after `category TEXT,` in `videos_new`;\n- add `language,` after `category,` in the INSERT list;\n- add `${languageExpr},` after `category,` in the SELECT list.\n\n`VideoUpsertRow` gains `language: string | null;` after `category`.\n\n`upsertStmt`:\n- the INSERT list gains `language,` after `category,`;\n- VALUES becomes 26 `?` followed by `NULL, NULL, 0`;\n- ON CONFLICT gains `language = excluded.language,` after `category = excluded.category,`.\n\n`upsertVideos` gains `row.language,` directly after `row.category,`.\n\nAlignment check: the column list, the `?` count and the `run()` arguments each gain exactly one entry, in the same slot.\n\nThis follows the plan and keeps `language` consistent with `category`: a re-crawl whose payload has `{id: null}` sets crawl.db's `language` to NULL. This is noted in the inventory and stays as is.\n\n### `videos-worker.ts`\n```ts\ninterface PeerTubeLanguage {\n  id?: string | null;\n  label?: string;\n}\n```\n`PeerTubeVideo` gains `language?: PeerTubeLanguage | string;` after `category`. `toVideoRow` gains `language: extractLanguage(video.language),` after `category:`.\n```ts\n/**\n * Handle extract language: the PeerTube language code (an object's id or a plain string), trimmed; null otherwise, including a null id.\n */\nfunction extractLanguage(value: PeerTubeVideo[\"language\"]): string | null {\n  const raw = value && typeof value === \"object\" ? value.id : value;\n  const code = typeof raw === \"string\" ? raw.trim() : \"\";\n  return code || null;\n}\n```\nThe trim makes this match the handler's `pick_text` exactly: numbers, `\"\"` and whitespace all give `null`.\n\n### Dist\nRun `cd engine/crawler && npm install && npm run build`, then commit `dist/db.js`, `dist/videos-worker.js` and any other file tsc rewrites (for example `host-filters.js`). Review the full dist diff.\n\n---\n\n## 5. Video page\n\n### `video-page.html` (between `video-meta-row` and `video-description`)\n```html\n            <div id=\"video-taxonomy\" class=\"video-taxonomy\" hidden>\n              <span id=\"video-category\" class=\"taxonomy-item\" hidden><span class=\"taxonomy-label\">Category</span><span id=\"video-category-value\" class=\"taxonomy-value\"></span></span>\n              <span id=\"video-language\" class=\"taxonomy-item\" hidden><span class=\"taxonomy-label\">Language</span><span id=\"video-language-value\" class=\"taxonomy-value\"></span></span>\n              <ul id=\"video-tags\" class=\"video-tags\" aria-label=\"Tags\"></ul>\n            </div>\n```\nThere are no inline styles, because of the CSP. Elements are hidden with the `hidden` attribute.\n\n### `index.ts`\nNew element lookups go with the others at the top:\n```ts\nconst taxonomyEl = document.getElementById(\"video-taxonomy\");\nconst categoryEl = document.getElementById(\"video-category\");\nconst categoryValueEl = document.getElementById(\"video-category-value\");\nconst languageEl = document.getElementById(\"video-language\");\nconst languageValueEl = document.getElementById(\"video-language-value\");\nconst tagsEl = document.getElementById(\"video-tags\");\n```\n\n`VideoMetadata` gains `tags?: string[]; category?: string; language?: string;`.\n\n`fetchVideoMetadataFromServer` return gains:\n```ts\n      tags: toStringList(data.tags),\n      category: typeof data.category === \"string\" ? data.category : \"\",\n      language: typeof data.language === \"string\" ? data.language : \"\",\n```\n\n`fetchVideoMetadataFromInstance` return gains:\n```ts\n      tags: toStringList(data.tags),\n      category: peerTubeLabel(data.category, false),\n      language: peerTubeLabel(data.language, true),\n```\n\nNew helpers, placed near `normalizeNumber`:\n```ts\n/**\n * Handle to string list: the string elements of an array, else [].\n */\nfunction toStringList(value: unknown): string[] {\n  return Array.isArray(value) ? value.filter((item): item is string => typeof item === \"string\") : [];\n}\n\n/**\n * Handle PeerTube label: the trimmed `label` of a `{id, label}` object; with requireId, \"\" when the id is null (PeerTube's unset value).\n */\nfunction peerTubeLabel(value: unknown, requireId: boolean): string {\n  if (!value || typeof value !== \"object\") return \"\";\n  const { id, label } = value as { id?: unknown; label?: unknown };\n  if (requireId && (id === null || id === undefined)) return \"\";\n  return typeof label === \"string\" ? label.trim() : \"\";\n}\n\n/**\n * Handle render taxonomy: category, language and tag chips via textContent only; the whole block is hidden when no metadata resolved.\n */\nfunction renderTaxonomy(metadata: VideoMetadata | null) {\n  if (!taxonomyEl) return;\n  taxonomyEl.hidden = !metadata;\n  if (!metadata) return;\n  setTaxonomyItem(categoryEl, categoryValueEl, metadata.category ?? \"\");\n  setTaxonomyItem(languageEl, languageValueEl, metadata.language ?? \"\");\n  if (tagsEl) {\n    const tags = metadata.tags ?? [];\n    const items = tags.map((tag) => {\n      const item = document.createElement(\"li\");\n      item.className = \"tag-chip\";\n      item.textContent = tag;\n      return item;\n    });\n    if (items.length === 0) {\n      const empty = document.createElement(\"li\");\n      empty.className = \"video-tags-empty\";\n      empty.textContent = \"No tags\";\n      items.push(empty);\n    }\n    tagsEl.replaceChildren(...items);\n  }\n}\n\n/**\n * Handle set taxonomy item: show the value, or hide the item when it is empty.\n */\nfunction setTaxonomyItem(itemEl: HTMLElement | null, valueEl: HTMLElement | null, value: string) {\n  if (valueEl) valueEl.textContent = value;\n  if (itemEl) itemEl.hidden = !value;\n}\n```\n`loadVideo` calls `renderTaxonomy(metadata);` directly before the `descriptionEl` block.\n\nDecisions:\n- **No metadata at all.** When both fetches fail, the block is hidden: nothing is known, so \"No tags\" would be a claim the page cannot make.\n- **Language.** The instance fallback hides a null-id language, which matches the server path.\n- **Category.** \"Unknown\" shows on both paths, following R2 literally.\n\n### `video.css` (after `.metric svg`)\n```css\n.video-taxonomy {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.5rem 0.8rem;\n  font-size: 0.85rem;\n  color: var(--muted);\n}\n\n.video-taxonomy[hidden],\n.video-taxonomy [hidden] {\n  display: none;\n}\n\n.taxonomy-item {\n  display: inline-flex;\n  align-items: baseline;\n  gap: 0.35rem;\n}\n\n.taxonomy-label {\n  font-size: 0.8rem;\n  text-transform: uppercase;\n  letter-spacing: 0.04em;\n}\n\n.taxonomy-value {\n  color: var(--accent-strong);\n  font-weight: 600;\n}\n\n.video-tags {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.35rem;\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n\n.tag-chip {\n  padding: 0.15rem 0.55rem;\n  border-radius: 999px;\n  background: rgba(180, 87, 55, 0.08);\n  color: var(--accent-strong);\n  font-size: 0.8rem;\n}\n\n.video-tags-empty {\n  font-style: italic;\n}\n```\nThe explicit `[hidden]` rule is needed because an author `display:` rule overrides the UA default.\n\n### `client/frontend/dist`\nRun `npm run build`, commit the new hashed `video-*.js` / `video-*.css` and `dist/video-page.html`, and delete the orphaned `video-gjYm1MC8.js` and `video-ypOuFwNw.css`, plus any re-hashed shared chunk.\n\n---\n\n## 6. Tests\n\n### `tests/active/test_video_handler.py` (new)\nModule docstring, in the suite's bullet style:\n```text\n\"\"\"`/api/video` (`handle_video_request`) refreshes the stored video from its source instance only when the video detail fetch returns a JSON object, answers from one merged value set, and maps category and language to PeerTube default labels; `migrate_whitelist_schema` adds `videos.language` to an existing whitelist DB.\n\n- A successful fetch writes the source title, description, stats, tags_json, category, language, nsfw, duration and thumbnail_url, moves last_checked_at forward, clears instances.last_error/_at/_source, and the response carries tags, category, language, nsfw, duration and thumbnailUrl.\n- A caught network error (the fetch stub returning None, and the real fetch with urlopen raising URLError) and a malformed body (not JSON, bad UTF-8, a JSON list) leave every videos and channels column and instances.last_error as they were, and the response equals the DB values.\n- A payload with stats but no tags or category keeps the stored tags_json and category; `tags: []` stores \"[]\" and answers `tags: []`.\n- A source change between two requests is reflected in the second response and in the DB.\n- A stored \"15\" answers \"Science & Technology\", \"99\" answers \"99\", \"Music\" answers \"Music\", \"en\" answers \"English\", \"zh-Hans\" answers \"Simplified Chinese\", \"xx\" answers \"xx\".\n- The migration adds `language` to a pre-change videos table, keeps every row and the three FTS triggers, and a second run changes nothing.\n\nThe DB schema, triggers included, comes from `sync-whitelist.py`; the instance is never contacted: `fetch_instance_json` or `urlopen` is replaced on `handlers.video`.\n\"\"\"\n```\n\nSetup, following `test_internal_events.py` and `test_repair_video_channel_names.py`:\n```python\nROOT = Path(__file__).resolve().parents[2]\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nAPI_DIR = SERVER_DIR / \"api\"\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nfor path in (SERVER_DIR, API_DIR):\n    if str(path) not in sys.path:\n        sys.path.insert(0, str(path))\n\nfrom handlers import video  # noqa: E402\n\nHOST = \"peer.example\"\nOLD_CHECKED_AT = 1_000\nVIDEO_PATH = \"/api/v1/videos/v1\"\nCHANNEL_PATH = \"/api/v1/video-channels/newslug\"\nPARAMS = {\"id\": [\"v1\"], \"host\": [HOST]}\nSOURCE = {\"name\": \"New title\", \"description\": \"New desc\", \"views\": 50, \"likes\": 5, \"dislikes\": 1, \"tags\": [\"alpha\", \"beta\"], \"category\": {\"id\": 15, \"label\": \"Science & Technology\"}, \"language\": {\"id\": \"en\", \"label\": \"English\"}, \"nsfw\": True, \"duration\": 321, \"thumbnailPath\": \"/static/thumbnails/new.jpg\", \"channel\": {\"name\": \"newslug\", \"displayName\": \"New Chan\"}}\n```\n\n**Fixtures:**\n- `_load_job(name, filename)`, copied from the repair test.\n- `sync_job` and `migrations`, module scope, loaded as `sync_whitelist_video_handler` and `whitelist_migrations_video_handler`.\n- `server(tmp_path, sync_job)`:\n  - opens `sqlite3.connect(tmp_path / \"whitelist.db\", check_same_thread=False)` and sets `row_factory = sqlite3.Row`;\n  - runs `ensure_whitelist_schema` and `ensure_content_schema`;\n  - seeds one `instances` row (`HOST`, `last_error='boom'`, `last_error_at=5`, `last_error_source='video'`);\n  - seeds one `channels` row (`'7', HOST, channel_name 'oldslug', display_name 'Old Chan', followers_count 3`);\n  - seeds one `videos` row with every column below:\n\n| Column | Value |\n|---|---|\n| `video_id` | `'v1'` |\n| `video_uuid` | `'uuid-1'` |\n| `instance_domain` | `HOST` |\n| `channel_id` | `'7'` |\n| `channel_name` | `'Old Chan'` |\n| `title` | `'Old title'` |\n| `description` | `'Old desc'` |\n| `tags_json` | `'[\"old\"]'` |\n| `category` | `'Music'` |\n| `language` | `'fr'` |\n| `nsfw` | `0` |\n| `duration` | `10` |\n| `thumbnail_url` | `'https://peer.example/old.jpg'` |\n| `views` | `1` |\n| `likes` | `1` |\n| `dislikes` | `0` |\n| `published_at` | `1_600_000_000_000` |\n| `last_checked_at` | `OLD_CHECKED_AT` |\n\n  - commits, and returns `SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)`;\n  - closes the connection on teardown.\n- `responses(monkeypatch)`: patches `video.respond_json` to append `(status, body)` and returns the list.\n- `_serve(monkeypatch, payloads: dict[str, dict | None])`: patches `video.fetch_instance_json` with `lambda host, path: payloads.get(path)`.\n- `_snapshot(conn)`: returns `SELECT * FROM videos WHERE video_id='v1'`, `SELECT * FROM channels`, and `SELECT last_error, last_error_at, last_error_source FROM instances`, each as a tuple of `tuple(row)`.\n- `_FakeResponse(body: bytes)`: `status = 200`, `__enter__` returns self, `__exit__` returns False, and `read()` returns the body.\n\n**Tests:**\n- `test_success_refreshes_row_and_response`. It serves `{VIDEO_PATH: SOURCE, CHANNEL_PATH: {\"followersCount\": 9}}`, calls `video.handle_video_request(None, server, PARAMS)`, and asserts:\n  - the DB row's title, description, views, likes, dislikes, tags_json, category, language, nsfw, duration and thumbnail_url equal `(\"New title\", \"New desc\", 50, 5, 1, '[\"alpha\", \"beta\"]', \"Science & Technology\", \"en\", 1, 321, \"https://peer.example/static/thumbnails/new.jpg\")`;\n  - `last_checked_at > OLD_CHECKED_AT`;\n  - `instances.last_error*` are all NULL;\n  - the response is status 200 with `tags == [\"alpha\", \"beta\"]`, `category == \"Science & Technology\"`, `language == \"English\"`, `nsfw is True`, `duration == 321` and `thumbnailUrl` equal to the stored URL;\n  - the 18 original keys are all still present.\n- `test_fetch_failure_leaves_db_untouched`, parametrised with ids:\n  - `stub-none`: `_serve` with `{}`;\n  - `urlopen-urlerror`: `monkeypatch.setattr(video, \"urlopen\", raising URLError(\"down\"))`;\n  - `not-json`: `urlopen` returns `_FakeResponse(b\"<html>\")`;\n  - `bad-utf8`: body `b\"\\xff\\xfe\"`;\n  - `json-list`: body `b\"[1, 2]\"`.\n\n  It asserts `_snapshot` is equal before and after (every column, `last_checked_at` included, `last_error == 'boom'`) and that the response is status 200 with `title == \"Old title\"`, `description == \"Old desc\"`, `views == 1`, `tags == [\"old\"]`, `category == \"Music\"`, `language == \"French\"`, `nsfw is False`, `duration == 10`, `thumbnailUrl == \"https://peer.example/old.jpg\"` and `channelName == \"Old Chan\"`.\n- `test_partial_payload_keeps_tags_and_category`. It serves `{VIDEO_PATH: {\"views\": 77}}` and asserts the DB has `views == 77`, `tags_json == '[\"old\"]'`, `category == \"Music\"` and `language == \"fr\"`, and the response has `tags == [\"old\"]` and `category == \"Music\"`.\n- `test_empty_tag_list_propagates`. It serves `{VIDEO_PATH: {\"tags\": []}}` and asserts the DB has `tags_json == \"[]\"` and the response has `tags == []`.\n- `test_second_request_reflects_source_change`. The first request uses `SOURCE`. The second uses `{**SOURCE, \"name\": \"Renamed\", \"tags\": [\"gamma\"]}`, with the same `payloads` dict mutated. It asserts the second response has title \"Renamed\" and tags `[\"gamma\"]`, and the DB has the same values.\n- `test_response_labels`, parametrised on `(category, language, expected_category, expected_language)`:\n  - `(\"15\", \"en\", \"Science & Technology\", \"English\")`;\n  - `(\"99\", \"zh-Hans\", \"99\", \"Simplified Chinese\")`;\n  - `(\"Music\", \"xx\", \"Music\", \"xx\")`.\n\n  It UPDATEs the seeded row, serves `{}` (so the answer comes from the DB), and asserts the response labels.\n- `test_migration_adds_language_column(tmp_path, sync_job, migrations)`:\n  - creates the pre-change `videos` table inline. Its DDL is the whitelist `videos` DDL without `language`, error columns included, so only the additive path runs;\n  - then runs `ensure_whitelist_schema` + `ensure_content_schema` (FTS and triggers are created, and `videos` is left as is), and inserts two videos;\n  - runs `migrations.migrate_whitelist_schema(conn, \"instances\")` and asserts:\n    - `\"language\"` is in the `PRAGMA table_info(videos)` names;\n    - the `SELECT video_id, title, tags_json, category FROM videos ORDER BY video_id` rows are unchanged, and `language` is NULL for both;\n    - `SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'videos_fts_%'` equals 3;\n    - a second run leaves the `PRAGMA table_info(videos)` output identical.\n\n### `tests/active/test_videos_worker.py`\n- Extract the body of the existing test into `_crawl(tmp_path, schema_sql: str, alpha_videos: list[dict]) -> tuple[Path, str, str, str, str, CompletedProcess]`. It holds the node, dist and git asserts, the two stand-ins, the seeding through `conn.executescript(schema_sql)` and the node run.\n- Existing test: alpha videos gain `\"language\": {\"id\": \"en\", \"label\": \"English\"}` (a-1) and `\"language\": {\"id\": None, \"label\": \"Unknown\"}` (a-2). It additionally asserts `SELECT video_id, language FROM videos` gives `{\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}`.\n- New `test_crawl_adds_language_to_existing_db`:\n  - `legacy = SCHEMA.read_text(encoding=\"utf-8\").replace(\"  language TEXT,\\n\", \"\")`, and it asserts `legacy != SCHEMA.read_text(...)` so the fixture really lacks the column;\n  - runs `_crawl` with alpha `[{\"uuid\": \"a-1\", \"name\": \"A one\", \"language\": \"de\"}]`;\n  - asserts `\"language\" in PRAGMA table_info(videos)` names and that a-1's `language == \"de\"`.\n- The docstring gains two bullets:\n  - \"Each video's `language` is the PeerTube language id, NULL for a null id or no language.\"\n  - \"A crawl.db created before `language` existed gains the column when the crawler opens it, and the crawl fills it.\"\n\n### Harvest-time (not in this worktree's code)\n- In `.un/skills/devsecops/config.json` `test_groups`, map the new test to `video.py`, `peertube_labels.py`, `whitelist_migrations.py` and `sync-whitelist.py`.\n- Extend `test_videos_worker.py`'s group with `src/db.ts`, `dist/db.js` and `schema.sql`.\n- The documentation checklist is settled and carried separately.\n\n---\n\n## Check against plan and requirements (ladder rung 2)\n\n### Pass 1\n**R1**\n- `fetch_instance_video_dynamic` returning `None` is the only success signal, and the guard is `dynamic is not None`.\n- Parse and non-dict failures return `None`; the kept exceptions and the non-200 case are unchanged.\n- A channel-detail failure still falls back.\n- A failure runs no statement at all.\n\n**R2**\n- Every field uses a present-and-valid-or-DB rule, and `thumbnail_url` maps `\"\"` to `None`.\n- `\"[]\"` propagates.\n- `extract_category` handles an id-only category, and a blank string keeps the DB value.\n- `language` holds the code, and a null id keeps the DB value.\n- There is one UPDATE path.\n\n**R3**\n- `schema.sql`, the `db.ts` ALTER, the rebuild and the upsert, `videos-worker.ts`, sync, the whitelist migration and its rebuild, `fetch_video_row` and the dist rebuild are all covered.\n\n**R4**\n- There is a stdlib map. The category lookup is digit-only, and unknown values stay raw.\n- The simplification is named in the module docstring.\n\n**R5**\n- There are six new keys with the specified types, and the 18 old keys are kept.\n- The proxy is untouched.\n\n**R6**\n- There is a block with hidden-when-empty category and language and a \"No tags\" state.\n- Both fetch paths fill it, and everything is set through `textContent` / `createElement`.\n- The CSS is compact and there are no inline styles.\n- The dist is rebuilt.\n\n**R7**\n- Every listed fixture maps to a test in the table at the top.\n- The failure assertions use full-row `SELECT *` snapshots.\n- The DB comes from the production schema helpers, and nothing touches the network.\n\n### Pass 1 findings, fixed in place\n- **Language rule divergence.** TS `toNullableString` does not trim, while Python `pick_text` does, so the two producers could store different values. `extractLanguage` now trims.\n- **Destructive migration path.** The legacy table in the migration test would otherwise have gone down the destructive rebuild path. It is now built with the error columns present.\n\n### Pass 2\nNothing unmet.\n\nThe simplifications, all named:\n- default-only labels (R4);\n- a whitespace-only language id is treated as absent on both producers;\n- the draft `LANGUAGE_LABELS` literal is marked for wholesale replacement from a stock instance before commit.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Two seams, each following an existing harness. (a) New `tests/active/test_video_handler.py::test_migration_adds_language_column`: it loads `sync-whitelist.py` and `whitelist_migrations.py` with `spec_from_file_location` (precedent: `test_repair_video_channel_names.py`) and builds the pre-change `videos` table inline in a tmp_path DB, error columns included and `language` left out. It runs `ensure_whitelist_schema` + `ensure_content_schema`, inserts two videos, and calls `migrate_whitelist_schema(conn, \"instances\")`. It then asserts that `language` is among the `PRAGMA table_info(videos)` names, that the `(video_id, title, tags_json, category)` rows are unchanged with `language` NULL, that 3 `videos_fts_%` triggers exist, and that a second run leaves `table_info` identical. (b) `tests/active/test_videos_worker.py`, which runs the committed `dist/videos-worker.js` under node against local PeerTube stand-ins, keeping its stale-dist and missing-tool guards. The existing case gains `language` on the alpha videos and asserts `{a-1: \"en\", a-2: None, b-1: None}`. The new `test_crawl_adds_language_to_existing_db` seeds crawl.db from `schema.sql` with the `language` line removed (asserting the text really differs) and asserts that the column exists after the crawl and that a-1 has `language == \"de\"`.</checkpoint>\n<name>language column in both producers</name>\n<intent>Every videos table the build touches has a nullable `language` column: `whitelist_migrations.migrate_whitelist_schema` adds it to an existing whitelist DB without losing rows or FTS triggers, and the crawler (`schema.sql`, `db.ts`, `videos-worker.ts`) stores each video's PeerTube language code in crawl.db, adding the column to a crawl.db that predates it.</intent>\n<clause_1>`migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing.</clause_1>\n<clause_2>A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed.</clause_2>\n<files>engine/crawler/schema.sql (EDITED), engine/crawler/src/db.ts (EDITED), engine/crawler/src/videos-worker.ts (EDITED), engine/crawler/dist/db.js (EDITED), engine/crawler/dist/videos-worker.js (EDITED), engine/server/db/jobs/whitelist_migrations.py (EDITED), engine/server/db/jobs/sync-whitelist.py (EDITED), tests/active/test_video_handler.py (NEW), tests/active/test_videos_worker.py (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>`tests/active/test_video_handler.py::test_response_labels`, parametrised on `(\"15\",\"en\")`, `(\"99\",\"zh-Hans\")` and `(\"Music\",\"xx\")`. The seam is `handlers.video.handle_video_request(None, server, params)`, imported with `engine/server` and `engine/server/api` on `sys.path` (precedent: `test_internal_events.py`). `server` is a `SimpleNamespace(db, db_lock, video_error_threshold, popularity_like_weight)` over a tmp_path DB built from `sync-whitelist.py`'s `ensure_whitelist_schema` + `ensure_content_schema` and seeded with one instance, one channel and one video. `video.respond_json` is monkeypatched to capture `(status, body)`, and `video.fetch_instance_json` is stubbed to return None, so the answer comes from the DB. The test UPDATEs the seeded row's category and language, then asserts that the response's `category` and `language` equal \"Science & Technology\"/\"English\", \"99\"/\"Simplified Chinese\" and \"Music\"/\"xx\", and that the stored values are still the raw id and code.</checkpoint>\n<name>default display labels in /api/video</name>\n<intent>The `/api/video` response built by `handle_video_request` carries `category` and `language` as PeerTube default display labels from the new `engine/server/data/peertube_labels.py`, while the stored values stay ids and codes.</intent>\n<clause_1>A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored.</clause_1>\n<clause_2>A stored language code is answered with its PeerTube default label, and an unknown code is answered raw.</clause_2>\n<files>engine/server/data/peertube_labels.py (NEW), engine/server/api/handlers/video.py (EDITED), tests/active/test_video_handler.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>This uses the same `handle_video_request` harness as phase 2, in `tests/active/test_video_handler.py`. Failure seam: `test_fetch_failure_leaves_db_untouched` is parametrised as `stub-none` (`fetch_instance_json` returns None), `urlopen-urlerror`, `not-json`, `bad-utf8` and `json-list`. The last four replace `video.urlopen` with a raiser or a `_FakeResponse`, so the real parse guard in `fetch_instance_json` runs. The test asserts that the `SELECT *` snapshots of the videos row, all channels rows and `instances.last_error*` are equal before and after, and that the status-200 response carries the DB values (title, description, views, tags [\"old\"], category \"Music\", language \"French\", nsfw False, duration 10, thumbnailUrl, channelName). Success seam: a path-keyed `fetch_instance_json` stub drives four tests. `test_success_refreshes_row_and_response` checks that every refreshed column is stored, that `last_checked_at` moved forward, that `instances.last_error*` is NULL, and that the response's new keys equal the stored values while the 18 original keys remain. `test_partial_payload_keeps_tags_and_category` checks that views update while the stored tags_json, category and language stay. `test_empty_tag_list_propagates` checks that \"[]\" is stored and `[]` is answered. `test_second_request_reflects_source_change` checks that the second response and the DB carry the renamed title and the new tags.</checkpoint>\n<name>refresh only on success, one merge</name>\n<intent>`handle_video_request` in `engine/server/api/handlers/video.py` writes to the DB only when the video detail fetch returns a JSON object, and on success it stores and answers one merged source-over-DB value set, including tags, category, language, nsfw, duration and thumbnail.</intent>\n<clause_1>A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values.</clause_1>\n<clause_2>A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values.</clause_2>\n<files>engine/server/api/handlers/video.py (EDITED), tests/active/test_video_handler.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>New `tests/active/test_frontend_video_taxonomy.py`, following the esbuild-bundle + node-runner precedent of `test_frontend_videos.py` / `test_frontend_blocks.py`. It bundles `client/frontend/src/pages/video-page/index.ts` with `client/frontend/node_modules/.bin/esbuild` (`--platform=node`, with a CSS loader or empty stub for `video.css`). A runner stubs the platform node lacks: a `document` whose `getElementById` returns a recorded stub element per id, with `createElement` and `replaceChildren`; `window.location.search` carrying `id` and `host`; `localStorage`/`sessionStorage`; and `fetch`, which returns a fixture body for `/api/video` and empty payloads elsewhere. After `loadVideo` settles, the runner reports the `textContent` and `hidden` of `video-category`, `video-category-value`, `video-language`, `video-language-value` and the `video-tags` children. Case 1 uses a body with category \"Science & Technology\", language \"English\" and tags [\"alpha\",\"beta\"], and asserts the two values are visible and there is one `tag-chip` per tag with the tag as its text. Case 2 uses a body with category \"\", language \"\" and tags [], and asserts the category and language items are hidden and the only tag child reads \"No tags\".</checkpoint>\n<name>taxonomy block on the video page</name>\n<intent>The video page (`video-page.html`, `pages/video-page/index.ts`, `video.css`) has a `video-taxonomy` block that shows the category, language and tags from `/api/video` as text only.</intent>\n<clause_1>For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag.</clause_1>\n<clause_2>For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads \"No tags\".</clause_2>\n<files>client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/src/video.css (EDITED), client/frontend/dist (EDITED, rebuilt; orphaned hashed video assets deleted), tests/active/test_frontend_video_taxonomy.py (NEW)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nPhase 1 needs `cd engine/crawler && npm install && npm run build` so the committed dist is current; otherwise `test_videos_worker.py` fails on a stale dist. Phase 2 needs a manual step: `LANGUAGE_LABELS` must be replaced wholesale with the JSON from a stock PeerTube instance's `GET /api/v1/videos/languages` (a live endpoint), as the settled draft requires; the checkpoint only asserts \"en\", \"zh-Hans\" and unknown codes, so it cannot catch a bad transcription. Phase 4 needs `client/frontend/node_modules` (esbuild) installed and `npm run build` for the committed dist. Deployment (after the merge, not a checkpoint): run the crawler once and `migrate-whitelist.py` on every whitelist.db before restarting the Engine.\n</needs_coordination>\n\n<rationale>\nThe step's {principles}, {shape_ladder-ladder} and {tdd_seams} placeholders arrived unrendered, so each seam is taken from an existing harness in tests/active rather than from those texts. The split follows dependency order and one seam per phase. Phase 1 is the schema in both producers: `fetch_video_row` will select `v.language`, so the handler phases cannot start before the column exists in the whitelist schema that their fixture builds, and the crawler half belongs here because it is the same column fact, checked through its own node harness. Phase 2 (labels) lands before phase 3 (the refresh gate) so phase 3's failure test can assert the DB answer in its final labelled form (\"French\") and nothing has to be rewritten later. The labels are also a separable concern: a pure display lookup exercised through the DB-only response path. Phase 3 holds the R1/R2/R5 core as two clauses, failure writes nothing and success writes and answers one merge. The partial-payload, empty-tags and second-request cases are instances of the merge clause, not separate facts. Phase 4 is the page: the settled draft had no test for R6, so the operator approved a new node/esbuild page-render checkpoint on the `test_frontend_videos.py` precedent. The instance-direct fallback path (`fetchVideoMetadataFromInstance`) is deliberately not checkpointed and was accepted as proposed. There is no prose phase, because the only prose (DATA_BUILD.md runbook order, harvest notes, the devsecops test_groups mapping) is documentation or harvest-time config, which Step 9 handles.\n</rationale>",
    "author:tests/tmp/test_10_video_metadata_completeness_phase1.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D1b\">\n<disposition>justified</disposition>\n<what>I narrowed the prose to what the test asserts. Line 1 now reads \"The whitelist and crawl.db `videos` tables gain a nullable `language` column, and a crawl fills crawl.db's with the PeerTube language code.\" Holding the PeerTube code is now claimed only for crawl.db, where :225 and :261 carry it. For the whitelist table the docstring now claims only a nullable column, which :115/:116 carry. The docstring no longer says anything about a sync moving a crawled code into whitelist `videos.language`, and that step is not in this phase's must_prove.</what>\n</item>\n<item id=\"D8b\">\n<disposition>justified</disposition>\n<what>I narrowed the prose on line 4. \"The committed `dist/videos-worker.js`\" is now \"The built `dist/videos-worker.js`, no older than its source\". That matches what `_require_built_crawler` enforces at :157/:158: the dist must exist and must not predate its source, checked by commit time when both files are clean and committed, and by mtime otherwise. The test no longer claims the dist must be committed.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. I took claim-audit recommendation 3 (the C1d gap: the index is not checked after the second run). New line :131 re-runs `_matches` after the second `migrate_whitelist_schema`, so it now fails on a second run that rebuilds `videos`, recreates the triggers and leaves `videos_fts` empty. I left recommendations 1 and 2 as recommendations, but their UNCARRIED rows D1b and D8b are covered by the prose edits in items. I did not take recommendations 4 (malformed `language` shapes) or 5 (the test name): the first goes beyond this phase's clauses, and renaming would not change what the test gates.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:115, :116, :117, :119, :120, :122, :128, :129, :130, :131. Checked after `migrate_whitelist_schema(conn, \"instances\")` runs on a pre-change whitelist videos table (the column's absence is confirmed at :109 and the triggers are confirmed at :110). There is exactly one `language` column (:115) and it is nullable (:116). The rows read back as literal seeds with language NULL (:117). The three `videos_fts_*` triggers are present (:119). MATCH still finds v1 (:120), and a row v3 inserted afterwards is also found (:122). A second run leaves table_info (:128), the rows (:129), the triggers (:130) and both MATCH results (:131) unchanged.</assertion>\n<expected>`language` table_info notnull 0. Rows [(\"v1\",\"Alpine walk\",'[\"hike\"]',\"Travels\",None), (\"v2\",\"Harbour night\",None,None,None)]. Triggers [ad, ai, au]. {\"v1\"} for \"Alpine\" and {\"v3\"} for \"Lantern\", before and after the second run. Second-run table_info and rows equal the first-run snapshots.</expected>\n<wrong_implementation>Today's migration adds nothing, so :115 finds 0 columns. A rebuild through `migrate_videos_schema` drops the triggers, so :119 reads []. A rebuild that never repopulates the index gives :120/:131 an empty set. An unconditional ALTER on the second run raises \"duplicate column name: language\". A second run that resets rows loses v3's 'fr', which fails :129.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:225, :257, :261. At :225, the built dist under node crawls two stand-ins and crawl.db holds {a-1: \"en\", a-2: None, b-1: None}. At :257 and :261, a crawl.db seeded from schema.sql with its language line stripped (absence confirmed at :247) gains the column (:257). The rows then read [(\"a-0\",\"Old one\",None), (\"a-1\",\"A one\",\"de\")] (:261).</assertion>\n<expected>{\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}. `language` is in the column names. [(\"a-0\",\"Old one\",None), (\"a-1\",\"A one\",\"de\")].</expected>\n<wrong_implementation>Storing the label gives \"English\"/\"Unknown\". Ignoring the field gives all None. A db.ts with no ALTER migration leaves the existing crawl.db without the column, so :257 fails. Adding language to the INSERT but not to `ON CONFLICT DO UPDATE SET` leaves a-1 NULL at :261. A column add that rebuilds the table without copying rows loses a-0.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every negative assertion (:109 and :247 for the column being absent) is a pre-state control, and a positive assertion after the code under test runs (:115 and :257) depends on it. If the migration or crawler code is deleted, :115, :225 and :257 go red.\n2. No. Expected values are literal seeds or literal stand-in payload ids, and the test never computes a language itself. :115 goes red if the ALTER in the whitelist migration is deleted, :225 if the `language?.id` mapping in videos-worker.ts is deleted, and :257 if the ADD COLUMN migration in db.ts is deleted.\n3. No. Language is read on three inputs (an id, `{\"id\": null}` and a missing field), across two instances, in both the insert and the conflict upsert paths.\n4. No. The only doubles are the PeerTube HTTP stand-ins, which fake an external service. The project's own migration code, the dist worker and db.js all run for real.\n5. Yes, it collects. The only new code is :131, which reuses `_matches`, `conn` and existing names. The file has the same three test functions as before, and the imports are unchanged.\n6. Yes. MATCH after a column add, the notnull flag, the trigger names and the crawler's upsert-over-an-existing-row behaviour were all observed in the earlier probes (probe_10_language.py and probe_10_crawl.py). The new :131 expects the same {\"v1\"}/{\"v3\"} values those probes saw after the ALTER.\n7. Yes, still red for its own reason. Today test 1 fails at :115 (the migration adds no column), and tests 2 and 3 fail at :221 and :257 (no language column in crawl.db). My edits only touched the docstring and added :131 after those failure points, so none of them adds a new way to fail first.\nNothing needed rewriting beyond the two docstring edits and the added :131 assertion.\n</answers>",
    "self_check:tests/tmp/test_10_video_metadata_completeness_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:115-116: after `migrate_whitelist_schema(conn, \"instances\")` on the pre-change whitelist.db, `PRAGMA table_info(videos)` has exactly one `language` row, and its notnull flag is 0</assertion>\n<expected>One `language` row with notnull 0. A probe using a plain `ALTER TABLE videos ADD COLUMN language TEXT` gave `(31, 'language', 'TEXT', 0, None, 0)`. Today's migration adds nothing, and the run fails at :115 with `assert 0 == 1`.</expected>\n<wrong_implementation>The migration is left as it is today, or only `ensure_content_schema`'s CREATE TABLE is updated, so an existing DB never gets the column: len(language) == 0. If it is added as `language TEXT NOT NULL DEFAULT ''`, notnull reads 1.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:117: `SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id` after the first migration</assertion>\n<expected>[(\"v1\", \"Alpine walk\", '[\"hike\"]', \"Travels\", None), (\"v2\", \"Harbour night\", None, None, None)]. The probe printed exactly these two rows after adding the column.</expected>\n<wrong_implementation>A rebuild migration (create videos_new, copy, drop, rename) whose column list leaves out tags_json/category, or that forgets the INSERT ... SELECT, reads back NULL tags/category or [] rows. A column added with a default such as 'und' reads 'und' where None is expected.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:119-122: after the migration, the three `videos_fts_*` triggers are still in sqlite_master; `title : \"Alpine\"` MATCH returns {\"v1\"}; a row inserted afterwards with `language='fr'` is found by `title : \"Lantern\"` as {\"v3\"}</assertion>\n<expected>[(\"videos_fts_ad\",), (\"videos_fts_ai\",), (\"videos_fts_au\",)], {\"v1\"} and {\"v3\"}. The probe printed all three after adding the column.</expected>\n<wrong_implementation>A table-rebuild migration that drops `videos` and takes the triggers with it (reads []). Or one that changes rowids so the external-content index no longer joins (the Alpine MATCH reads set()). Or one that leaves the ai trigger missing (the Lantern MATCH reads set()).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:128-130: a second `migrate_whitelist_schema` leaves `table_info`, the rows (including v3's 'fr') and the trigger list identical to the state after the first run. That first state is pinned to literals at :115-122.</assertion>\n<expected>Identical to the first run's state. The probe got `duplicate column name: language` from a second unguarded ALTER, so any guard has to be real.</expected>\n<wrong_implementation>An unguarded ALTER TABLE raises OperationalError \"duplicate column name: language\" on the second run. A migration that rebuilds on every run drops and recreates the triggers or rewrites the rows, which differ if the rebuild loses the 'fr' value or a column.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:224: after the committed dist/videos-worker.js crawls two stand-in channels, crawl.db's {video_id: language} is exactly {\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}</assertion>\n<expected>{\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}. The run showed the crawl reaching both stand-ins and storing all three videos (\"finished new_total=3\"). It stops at the supporting column check at :220 because crawl.db has no language column yet.</expected>\n<wrong_implementation>Not writing language at all: the column is missing or all three values are None. Storing `language.label` gives \"English\". Storing `JSON.stringify(language)` gives '{\"id\":\"en\",...}'. `String(language?.id)` stores \"null\"/\"undefined\" for a-2/b-1. Crashing on a video with no `language` drops b-1.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:256: on a crawl.db built from schema.sql with any language line stripped (control at :246 confirms the column is absent), the crawl leaves videos.language present</assertion>\n<expected>\"language\" in the column names. The run failed here with `assert 'language' in [...]` after \"finished new_total=1\", so the crawl ran and the column is what's missing.</expected>\n<wrong_implementation>Adding `language TEXT` only to schema.sql's CREATE TABLE IF NOT EXISTS, with no migration in db.ts: an existing crawl.db never gets the column, and the upsert naming it would fail or the column stays missing.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:260: `SELECT video_id, title, language FROM videos ORDER BY video_id` after the crawl over that pre-change crawl.db</assertion>\n<expected>[(\"a-0\", \"Old one\", None), (\"a-1\", \"A one\", \"de\")]. The probe on today's code gave rows [('a-0', 'Old one'), ('a-1', 'A one'), ...]: the unserved a-0 survives and a-1's title is overwritten by the upsert. So the harness reaches the conflict path.</expected>\n<wrong_implementation>A migration that recreates the videos table loses a-0 (reads only [(\"a-1\", ...)]). An upsert whose ON CONFLICT DO UPDATE SET list leaves out language keeps a-1's language None (\"A one\", None) even though the insert values carry \"de\".</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, every docstring clause is tested. The migration clause is covered by :115-130 (column added and nullable, rows unchanged, triggers kept, MATCH works on the old row and on a new one, second run identical). The per-video language codes (en / {\"id\": null} / absent) are :224. Pre-change crawl.db gaining the column, a-0 kept NULL, a-1 set to \"de\" is :256 and :260. Missing node or git, missing or stale dist, and a nonzero node exit all fail via asserts in `_require_built_crawler` and at :216/:252; nothing calls skip. The docstring said \"its one language line removed\", but that only holds after the phase, so I changed it to \"any language line removed\" to match the fix in 9.\n2. Absence only: no. The negative checks are the pre-migration \"language not in columns\" (:109, :246), and they are controls: each is followed by a positive assertion that the column is present afterwards (:115, :256). The None values at :224 and :260 sit next to non-None values from the same run (\"en\", \"de\"), and the dict or list equality also requires every row to exist.\n3. Echoed literal: no. Every expected value is a literal, never recomputed by the test. Deleting the new column-add in `migrate_whitelist_schema` turns :115 red. Deleting the `language` mapping in videos-worker.ts, or leaving language out of db.ts's upsert column/SET list, turns :224/:260 red. Deleting db.ts's ALTER for existing DBs turns :256 red.\n4. One value: no. The crawler is read at four inputs: \"en\", {\"id\": null}, missing language, and \"de\" through the conflict path. Two different codes rule out a hardcoded constant. The idempotence checks at :128-130 compare against the first run's state, but that state is pinned to literals at :115-122 first.\n5. The double: no. The only doubles are the local HTTP servers standing in for remote PeerTube instances, which is a severed external layer. The whitelist job modules, the compiled crawler and sqlite are all real.\n6. It collects: yes, and the count matches. The supplied `--collect-only` summary printed \"no tests\", but the real run printed \"collected 3 items\", which is the three test functions I wrote. Every name used exists in the file (`_column_names`, `_table_info`, `_matches`, `_require_built_crawler`, `_instance`, `_crawl`, `_stop`). `ensure_whitelist_schema`, `ensure_content_schema` and `migrate_whitelist_schema(conn, \"instances\")` were all called successfully in probe_10_language.py.\n7. Observed, not predicted: yes, for every value. probe_10_language.py (re-run this turn) printed the pre-change columns, the triggers [('videos_fts_ad',), ('videos_fts_ai',), ('videos_fts_au',)], `(31, 'language', 'TEXT', 0, None, 0)`, MATCH [('v1',)] and [('v3',)], the rows `[('v1', 'Alpine walk', '[\"hike\"]', 'Travels', None), ('v2', 'Harbour night', None, None, None), ...]`, \"duplicate column name: language\" on a second ALTER, and a subn count of 1 on a language line. probe_10_crawl.py (re-run) showed \"rc 0\" and rows [('a-0', 'Old one'), ('a-1', 'A one'), ('a-2', 'A two')], so the stand-ins, the crawl and the upsert-overwrites-title path all work. The probes are still under tests/tmp/ because I have no delete tool; they can be removed now that the test carries what they showed.\n8. Red, not green: yes, red. The final run printed \"3 failed\", exit status 1.\n9. Red for the right reason: on the FIRST run, no. test_crawl_adds_language_to_existing_db failed its CONTROL at :230, `assert removed == 1`, with \"schema.sql does not carry exactly one language line to strip ... assert 0 == 1\". The test assumed the post-phase schema.sql, so it never reached the crawl. test_crawl_stores_each_videos_language failed with `sqlite3.OperationalError: no such column: language` at :220, a query error rather than an assertion. Rewrite: the strip now accepts 0 or 1 lines (`assert removed <= 1`, :232). The real premise is carried by the existing control `\"language\" not in _column_names(conn)` at :246, which works before and after the phase. I added a supporting assertion at :220, `\"language\" in _column_names(conn)`, so test 2 fails on an assertion instead of an OperationalError. After the rewrite, all three fail on the phase's own claims and no control failed. test_migration_adds_language_column fails at :115 `assert len(language) == 1` with \"assert 0 == 1 / where 0 = len([])\". test_crawl_stores_each_videos_language fails at :220 with \"crawl.db has no videos.language after the crawl\", after the log shows \"[videos] finished new_total=3\" and node exited 0 (the :216 control passed). test_crawl_adds_language_to_existing_db passes the controls at :232, :246 and :252, then fails at :256 `assert 'language' in [...]` after \"[videos] finished new_total=1\".\n10. Observed expected output: every `expected` column matches what the runs showed: the probe outputs quoted in 7 and the failure lines quoted in 9. The runs cannot show the post-phase language values yet (\"en\", \"de\", None), because the column does not exist yet. Those are the phase's claims, and they rest on the observed mechanics: the stand-ins are reached, the rows are written, and a-1's upsert conflict path runs.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### engine/crawler/schema.sql\n- Added `language TEXT,` after `category TEXT,` in `videos`. No index, because the first `db.exec(schemaSql)` runs against old tables.\n\n### engine/crawler/src/db.ts\n- New `migrateVideosLanguage(db)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`.\n- `applyBaseSchema` calls it after `migrateVideos` and before the second `db.exec(schemaSql)`, so a table the old rebuild just produced also gets the column.\n- The `migrateVideos` rebuild carries `language`: new `hasLanguage`/`languageExpr`, `language TEXT` in `videos_new`, and `language` / `${languageExpr}` after `category` in the INSERT and SELECT lists.\n- `VideoUpsertRow` has a new field `language: string | null`.\n- The upsert has `language` in its INSERT list, 26 `?` before `NULL, NULL, 0`, and `language = excluded.language` in ON CONFLICT. `upsertVideos` passes `row.language` right after `row.category`.\n- As the plan says, a re-crawl whose payload has `{id: null}` overwrites crawl.db's `language` with NULL. That matches how `category` is handled.\n\n### engine/crawler/src/videos-worker.ts\n- New `PeerTubeLanguage` interface `{ id?: string | null; label?: string }`, and `PeerTubeVideo.language?: PeerTubeLanguage | string`.\n- New `extractLanguage`: takes an object's `id` or a plain string, trimmed; a null id, a number, `\"\"` or whitespace gives `null`.\n- `toVideoRow` sets `language: extractLanguage(video.language)`.\n\n### engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js\n- Hand-edited to match the source changes above, in tsc's output style: 4-space indent, bodies of one-line `if`s on their own line, JSDoc kept. I couldn't run `npm run build`.\n- A throwaway probe (below) ran the edited dist under node against a local PeerTube stand-in. It exited with code 0, and the pre-change crawl.db gained `language` as its last column.\n- Rows it produced: `a-0` \"Old\" not revisited, `language` NULL; `a-1` title updated to \"A one\" through the conflict path, `language` \"de\"; `{id: null}` gave NULL; a video with no `language` gave NULL.\n- Both dist files were written after their sources, so the checkpoint's mtime staleness check passes while they are uncommitted.\n- Recommended before commit, but not needed for the checkpoint: run `cd engine/crawler && npm install && npm run build` and review the dist diff, so the committed dist is real tsc output.\n\n### engine/server/db/jobs/whitelist_migrations.py\n- New `migrate_videos_language(conn)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`. Rows, `videos_fts` and its triggers are untouched, and a second run does nothing.\n- `migrate_whitelist_schema` calls it last, after `migrate_videos_schema`.\n- The `migrate_videos_schema` rebuild carries `language` conditionally (`has_language`/`language_expr`; column after `category` in `videos_new`, the INSERT list and the SELECT list), so no rebuild can drop it.\n\n### engine/server/db/jobs/sync-whitelist.py\n- `ensure_content_schema`'s `CREATE TABLE videos` has a new `language TEXT,` after `category TEXT,`.\n- Nothing else changes: `VIDEO_COLUMNS` is parsed from `schema.sql`, so the exact check, the superset check and the copy column list all pick `language` up automatically.\n\n### tests/tmp/probe_10_dist_language.py\n- The throwaway probe described above. I have no delete tool, so I overwrote it with an empty file; it collects no tests. Please delete it.\n\n### Not touched\n- `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are in the phase's files list, but they are test files that the checkpoint promotion carries. This step is production code only, so I left them alone.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_10_dist_language.py - a throwaway probe used to watch the hand-edited dist run under node. Emptied, because I have no tool that deletes files; the operator should remove it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_10_video_metadata_completeness_phase2.py": "<assertions>\ntests/tmp/test_10_video_metadata_completeness_phase2.py:79 - `handle_video_request` sends exactly one response. This guards the capture the other assertions read. (setup, all clauses)\ntests/tmp/test_10_video_metadata_completeness_phase2.py:81 - that response has status 200, so the row was found and the answer came from the DB path. (setup, all clauses)\ntests/tmp/test_10_video_metadata_completeness_phase2.py:82 - the response `category` is the PeerTube default label for a stored digit-only id: \"15\" \u2192 \"Science & Technology\", and \"18\" \u2192 \"Food\" (the last default id). An unknown id is answered as stored: \"99\", and \"19\" (one past the default range). A text category is answered as stored: \"Music\". A missing key reads \"MISSING\", so an unchanged handler fails here instead of raising KeyError. A hard-coded label fails because the five cases disagree, and so does an off-by-one range or a map applied to text. # C1\ntests/tmp/test_10_video_metadata_completeness_phase2.py:83 - the response `language` is the PeerTube default label for a stored code: \"en\" \u2192 \"English\", \"zh-Hans\" \u2192 \"Simplified Chinese\" (a case-sensitive code). An unknown code \"xx\" is answered raw as \"xx\". A `fetch_video_row` that never selects `v.language` gives \"\" or \"MISSING\" and fails. # C2\ntests/tmp/test_10_video_metadata_completeness_phase2.py:86 - after the request the stored `(category, language)` still equals the raw id and code the test wrote. This catches an implementation that relabels before the handler's existing UPDATE and so writes labels back into the row. # C1 C2\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/probe_10_phase2_labels.py\", \"-s\"]. The probe used the checkpoint's harness: tmp_path DB from sync-whitelist.py `ensure_whitelist_schema` + `ensure_content_schema`, one instance, one channel and one video seeded, the row UPDATEd to (\"15\", \"en\"), `respond_json` captured, and `fetch_instance_json` stubbed to None. It printed:\n- videos columns include `language` (phase 1 is in place), and instances has `last_error`, `last_error_at` and `last_error_source`.\n- `handle_video_request` returned True and called `fetch_instance_json` once, with ('peer.example', '/api/v1/videos/v1').\n- It sent one response: 200 with the 18 existing keys and no `category` or `language` key.\n- Stored (category, language) after the request was ('15', 'en'). `last_checked_at` was bumped, which is the phase-3 defect and not asserted here.\nCommand: ValidateTests [\"tests/tmp/test_10_video_metadata_completeness_phase2.py\"] against the current tree. All 5 cases fail at line 82 with `assert 'MISSING' == <expected>`, which is the intended red: setup and the 200 status pass. The probe file could not be deleted with the tools I have, so I emptied it. It collects no tests; please remove tests/tmp/probe_10_phase2_labels.py.\nNot observed: the language labels \"English\" and \"Simplified Chinese\" were not checked against a running PeerTube instance, because there is no network. They come from the Step 6 checkpoint and the plan's R4 draft, which match PeerTube's `buildLanguages()` (`languages['zh-Hans'] = 'Simplified Chinese'`) as I recall it. A `GET /api/v1/videos/languages` on a stock instance would confirm them. The same call is the step the plan already needs for replacing `LANGUAGE_LABELS`. \"Science & Technology\", \"Food\" and the 1\u201318 range come straight from R4's list.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_10_video_metadata_completeness_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase2.py:82 \u2014 `body.get(\"category\", \"MISSING\") == expected_category` over five DB-only cases (fetch stubbed to None): \"15\"\u2192\"Science & Technology\", \"18\"\u2192\"Food\", \"99\"\u2192\"99\", \"19\"\u2192\"19\", \"Music\"\u2192\"Music\"; backed on a success refresh by :104 (`category == \"Science & Technology\"` for a stored \"15\") and :103 (stored category is still \"15\")</assertion>\n<expected>\"Science & Technology\", \"Food\", \"99\", \"19\", \"Music\" for the five cases, and \"Science & Technology\" at :104. The current code sends no `category` key at all; the run showed 'MISSING' at :82 in all five cases and at :104.</expected>\n<wrong_implementation>No mapping, just adding `\"category\": category` to the response: \"15\" and \"18\" answer raw \"15\"/\"18\", red. A map missing an entry or shifted by one (e.g. only ids 1\u201317): \"18\" answers \"18\" instead of \"Food\", red. A lookup that returns \"\" or None for an unknown id, or one that tries int() on any value: \"99\", \"19\" or \"Music\" answers \"\"/None or raises, red. A handler that turns the stored value into the label before the UPDATE and writes it back: :103 reads \"Science & Technology\" instead of \"15\", red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase2.py:83 \u2014 `body.get(\"language\", \"MISSING\") == expected_language` over \"en\"\u2192\"English\", \"zh-Hans\"\u2192\"Simplified Chinese\", \"xx\"\u2192\"xx\"; backed by :105 (`language == \"English\"` on a success refresh with stored \"en\") and :103 (stored language is still \"en\")</assertion>\n<expected>\"English\", \"Simplified Chinese\", \"xx\", and \"English\" at :105. The current code sends no `language` key: the probe's captured body had no `language` at all, so today :83 and :105 read 'MISSING'. The run never reached them because the category check fails first.</expected>\n<wrong_implementation>Sending the raw code (`\"language\": row[\"language\"]`): \"en\" answers \"en\", red. A lookup that lowercases or strips the region part: \"zh-Hans\" becomes \"zh-hans\" or \"zh\" and answers raw or \"Chinese\" instead of \"Simplified Chinese\", red. An unknown code mapped to \"\" or \"Unknown\": \"xx\" answers that, red. Not selecting `v.language` in `fetch_video_row`: every case answers \"\"/MISSING, red. Writing the label back into the row: :103 reads \"English\", red.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 the first version was a yes. The docstring's third claim (the row keeps the raw category and language) was only checked on the fetch-None path. By the plan's own phase 3 (R1), a failed fetch writes nothing, so after that phase the check would pass without measuring anything. I moved that claim onto a new success-refresh test, `test_refresh_stores_raw_codes`, and rewrote the bullet to say that. Each docstring bullet now has an assertion: bullet 1 \u2192 :82, bullet 2 \u2192 :83, bullet 3 \u2192 :102\u2013105.\n2. Absence only \u2014 the first version was a yes. The old :86 said \"stored unchanged\" with nothing proving a write happened. The probe showed the fetch-None path writes today only because of the always-truthy `dynamic` defect (last_checked_at 1000 \u2192 1790555448047, last_error cleared), which phase 3 removes. Rewrite: that no-change check now sits in the success test at :103. Before it, :102 checks that the refresh actually wrote the row (title == \"New title\" and last_checked_at > 1000). The run showed :102 and :103 passing today before the test went red at :104, so the control is live.\n3. Echoed literal \u2014 no. The expected labels are the plan's R4 literals (\"15\" Science & Technology, \"18\" Food; \"en\" English, \"zh-Hans\" Simplified Chinese), not computed in the test, and the test never calls a mapping itself. Deleting the response's `\"category\": ...` / `\"language\": ...` entries (or the lookup call that fills them) in `handle_video_request` turns :82/:83/:104/:105 red.\n4. One value \u2014 no. C1 is read at five inputs: two known ids including the top of the range (15, 18), the first unknown id (19), a far unknown (99) and a text value (Music). C2 is read at three inputs: plain, region-cased and unknown. Expected values come from the plan's literal table, not from another output of the handler.\n5. The double \u2014 no project module is replaced. `respond_json` (HTTP write) and `fetch_instance_json` (network) are cut off at the handler module's edge. The DB schema, `fetch_video_row`, `fetch_instance_video_dynamic`, the merge and the UPDATE are all real.\n6. It collects \u2014 the supplied `--collect-only` output read \"no tests\", which does not match. My run of the file shows \"collected 6 items\" (5 parametrised `test_response_labels` + `test_refresh_stores_raw_codes`), which matches what is written. Every import binds, and `sync_job.ensure_whitelist_schema` / `ensure_content_schema` exist (the fixture runs). `stored[...]` works because the fixture sets `row_factory = sqlite3.Row`.\n7. Observed, not predicted \u2014 the response shape and the DB effects come from runs of `tests/tmp/probe_10_phase2_shape.py` (emptied afterwards):\n   - fetch-None: the body has 18 keys and no `category` or `language`; the row stays '15'/'en'; last_checked_at is bumped.\n   - success stub: calls == ['/api/v1/videos/v1']; title \"New title\" is stored, category/language stay '15'/'en', and the body again has no category or language.\n   The label strings themselves are the plan's R4 literals (docs/project/plans/19-10-video-metadata-completeness.md:60, 945, 987). They cannot be observed until the phase exists; they are the spec, not an observed output.\n8. Red, not green \u2014 yes, red. The run printed \"tests/tmp/test_10_video_metadata_completeness_phase2.py  6 failed\", \"[exit status 1]\", \"collected 6 items\".\n9. Red for the right reason \u2014 yes. Every failure is on a phase assertion, not a control:\n   - `test_response_labels` \u00d7 5 failed at \"tests/tmp/test_10_video_metadata_completeness_phase2.py:82: AssertionError\" on \"assert 'MISSING' == 'Science & Technology'\" / \"'MISSING' == '99'\" / \"'MISSING' == 'Music'\" / \"'MISSING' == 'Food'\" / \"'MISSING' == '19'\".\n   - `test_refresh_stores_raw_codes` failed at \":104: AssertionError\" on \"assert 'MISSING' == 'Science & Technology'\".\n   All controls before them passed: one response, status 200, and in the new test the write control at :102 and the stored-raw check at :103. The only cause is that the response has no `category` key yet.\n10. Observed expected output \u2014 the rows' \"current\" values are what the run showed: 'MISSING' at :82 and :104. For :83 and :105 the run stopped earlier, but the probe's captured body had no `language` key, so they read 'MISSING' today. The rows' \"right implementation\" values are the plan's R4 literals, not something a run can show before the phase is built.\nRewritten this turn: the stored-raw check was removed from the fetch-None test, a new `test_refresh_stores_raw_codes` was added with a positive write control, and the third docstring bullet was updated. The probe file `tests/tmp/probe_10_phase2_shape.py` was emptied (I have no delete tool) and can be removed with the other tmp probes.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### engine/server/data/peertube_labels.py (NEW)\n- A stdlib-only module that follows the `data/*.py` style: a module docstring, `from __future__ import annotations`, and a docstring on each function. It does no work at import beyond the literals.\n- `CATEGORY_LABELS` maps `\"1\"`\u2013`\"18\"` to exactly the labels listed in R4. A `rat-tail:` comment names the ceiling (stock PeerTube lists only; plugin-added or renamed entries show raw) and the upgrade path (cache each instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`).\n- `LANGUAGE_LABELS` is the stock instance's `GET /api/v1/videos/languages` body that the operator pasted during this step, copied verbatim onto one line. This is the Step 6 manual replacement, and the plan's from-memory draft was never committed. The live list differs from the draft in places: `es` is \"Spanish (Spain)\", `pt` is \"Portuguese (Brazilian)\", `km` is \"Khmer\", and it adds `es-419`, `ca-valencia`, `zxx`, `gcf`, `gcr`, `rcf`, `gsw`, `sh` and `fse`. `en` \u2192 \"English\" and `zh-Hans` \u2192 \"Simplified Chinese\" are both there.\n- `category_label(value)`: returns `\"\"` when the value is empty or not a string. A string that is all ASCII digits (`isascii()` plus `isdigit()`) goes through the map, and an unknown id comes back unchanged. Any other value is returned as it is.\n- `language_label(value)`: returns `\"\"` when the value is empty or not a string. Otherwise it does a case-sensitive lookup, and an unknown code comes back raw.\n\n### engine/server/api/handlers/video.py (EDITED)\n- Imports `category_label` and `language_label` from `data.peertube_labels`.\n- `fetch_video_row` now also selects `v.language`.\n- The response dict gains two keys, and all existing keys are unchanged:\n  - `\"category\"`: `category_label(category)`. `category` is the existing merged value (source first, then the DB).\n  - `\"language\"`: `language_label(row.get(\"language\"))`.\n- Labels are applied only when building the response. The UPDATE still writes the raw merged `category`, and `language` is not written at all yet, so the stored id and code stay as they were. That is what `test_refresh_stores_raw_codes` checks.\n- Not in this phase: language merging from the source, the success-only write guard and the other R5 keys. They belong to Phase 3.\n\n### tests/active/test_video_handler.py\n- Not touched. It is on the phase's files list, but it holds the checkpoint that checkpoint promotion carries. This step is production code only.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_10_video_metadata_completeness_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C1d\">\n<disposition>fixed</disposition>\n<what>`STORED_ANSWER` (:46) now includes `\"likes\": 1, \"dislikes\": 0, \"subscribersCount\": 3`, which are the seeded videos.likes, videos.dislikes and channels.followers_count. So :151 (`_answered(body, STORED_ANSWER) == STORED_ANSWER`) now checks all three on every failure kind. This rules out a failure path that answers None, 0 or a default for them. The failure-bullet docstring now names likes, dislikes and subscriber count.</what>\n</item>\n<item id=\"C2d\">\n<disposition>fixed</disposition>\n<what>There are two new assertions. (a) :197 in `test_partial_payload_keeps_tags_and_category`: `_snapshot(server.db)[1] == channels_before`. Every `SELECT *` channels row must match the pre-request snapshot on a success where the payload has no channel. This rules out NULL slug, display name or followers being written into `channels`. (b) The new `test_failed_channel_fetch_keeps_stored_followers`: the detail fetch returns SOURCE, and the `/api/v1/video-channels/newslug` fetch raises `URLError`, which :210 confirms was attempted. :211 asserts the channels row is (\"newslug\", \"New Chan\", 3). Slug and display name are present, so they are written. Followers are absent, so the stored 3 stays. This rules out NULL or 0 followers after a failed channel-detail fetch. Both expected values were observed in a probe run. The docstring now states both behaviours.</what>\n</item>\n<item id=\"C2g\">\n<disposition>fixed</disposition>\n<what>`expected = {**STORED_ANSWER, \"views\": 77}` (:198) now includes likes 1, dislikes 0 and subscribersCount 3 through the widened `STORED_ANSWER`. So :199 requires the absent-field response to match the row pinned at :196 and the channels row pinned at :197. :212 also asserts that `subscribersCount` is 3 after a failed channel fetch.</what>\n</item>\n<item id=\"D13b\">\n<disposition>fixed</disposition>\n<what>This is the same change as C2g. :199 now checks that omitted likes and dislikes answer the stored 1 and 0, and subscribersCount the stored 3. The docstring's partial bullet also now says the channels row is left as it was.</what>\n</item>\n</items>\n\n<findings_addressed>\nclaim CRITICAL 1 (C1d, :150): I added likes 1, dislikes 0 and subscribersCount 3 to `STORED_ANSWER`, so the failure-response assertion (now :151) checks them on all five failure kinds.\nclaim CRITICAL 2 (C2d, :194): I added :197, which checks that the channels rows are unchanged on an absent-channel success. I also added `test_failed_channel_fetch_keeps_stored_followers` (:203\u2013:212), which checks the channels row (\"newslug\", \"New Chan\", 3) and subscribersCount 3 when the channel-detail fetch fails.\nclaim CRITICAL 3 (C2g/D13b, :195): the widened `STORED_ANSWER` puts likes, dislikes and subscribersCount into `expected` at :198, so the response at :199 has to match the row at :196.\nshape audit: no CRITICAL. The new assertions compare against seeded literals and probe-observed values, not a copy of the production mapping. Recommendations 1\u20133 were not taken, to keep this round inside the ledger.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:150 \u2014 the full videos row, every channels row and instances.last_error* all equal the pre-request snapshot, for URLError, 404, not-json, bad-utf8 and json-list. :151 \u2014 the response answers STORED_ANSWER: title, description, views 1, likes 1, dislikes 0, tags [\"old\"], category \"Music\", language \"French\", duration 10, the old thumbnail, channelName \"Old Chan\", subscribersCount 3. :152 \u2014 nsfw is False.</assertion>\n<expected>Snapshot unchanged, including (\"boom\", 5, \"video\"). The response carries the seeded DB values, and nsfw is the bool False.</expected>\n<wrong_implementation>Today's code writes on URLError and 404: last_checked_at goes 1000 \u2192 now, popularity moves, and the instance error is cleared. The three bad bodies raise. A failure path that answers None or a default for likes, dislikes or subscribersCount, or leaves out tags, duration or thumbnailUrl (\"MISSING\"), fails :151.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:164/:166/:168/:169/:170/:171/:173/:174 \u2014 full SOURCE: row, channels, cleared error, original keys and merged response. :196/:197/:199/:200 \u2014 absent and null-or-blank payloads: the row keeps the seed except views 77, channels rows are unchanged, and the response is STORED_ANSWER with views 77 (likes 1, dislikes 0, subscribersCount 3 included) and nsfw False. :211/:212 \u2014 failed channel-detail fetch: channels (\"newslug\", \"New Chan\", 3), and the response channelName \"New Chan\" with subscribersCount 3. :221/:222 \u2014 tags [] stores \"[]\" and answers []. :234\u2013:236 \u2014 an object body, {} included, is a success. :248/:250 \u2014 the second request reflects the source change.</assertion>\n<expected>Source values where present, DB values where absent, in the videos row, the channels row and the response alike.</expected>\n<wrong_implementation>Today's code leaves language \"fr\", duration 10 and the old thumbnail in the row after a full payload (fails :168). It answers no tags, duration or thumbnailUrl (fails :199 as \"MISSING\", observed). A merge that writes NULL followers after a failed channel fetch fails :211. One that nulls the channel slug or display name on an absent channel fails :197. A response that disagrees with the row on likes, dislikes or subscribersCount fails :199.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every unchanged-state check has a positive control: :148 shows the fetch was attempted, :195 shows the row was written, and :210 shows the channel fetch was attempted and failed.\n2. No. Expected values are seeded literals or probe-observed source values. Deleting the `row.get(\"channel_followers_count\")` fallback in `handle_video_request` turns :211/:212 red, and the same goes for the row/likes fallbacks at :199.\n3. No. subscribersCount is read at 3 (stored, on failure, partial and failed-channel runs) and 9 (source). Likes/dislikes are read at 1/0 (stored) and 5/1 (source).\n4. No. Only `respond_json` and `urlopen` are replaced. Both are severed I/O layers, and the project's `fetch_instance_json` runs for real.\n5. Yes, it collects. I imported the module's tests into a probe and ran it: 8 cases collected, with no import or name errors.\n6. Yes. Likes 1, dislikes 0 and subscribersCount 3 on failure and partial paths, the call list [video, channel], and channels (\"newslug\", \"New Chan\", 3) after a failed channel fetch were all observed in a probe run (tests/tmp/probe_10_phase3_channels.py) before I wrote them down. The probe file is now empty, since I have no delete tool, so the operator should remove it along with tests/tmp/probe_10_phase3_refresh.py.\n7. Yes, it is still red for the phase. The probe run of the edited test showed the failure cases red at :150 (the DB was written) or raising in the fetch (JSONDecodeError, UnicodeDecodeError, AttributeError), and the partial cases red at :199 on missing tags, duration and thumbnailUrl. The new `test_failed_channel_fetch_keeps_stored_followers` passes against today's code. It guards behaviour that already exists and that the phase must keep, and it is not a gap the phase fills.\n</answers>",
    "self_check:tests/tmp/test_10_video_metadata_completeness_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:149 \u2014 for all five failures (urlopen raising URLError, a 404 status whose body is `{}`, `<html>`, `\\xff\\xfe`, `[1, 2]`, each served by a fake `urlopen` so the real `fetch_instance_json` runs), the `SELECT *` videos row, every `SELECT *` channels row and `instances.last_error*` equal the snapshot taken before the request</assertion>\n<expected>The snapshot is unchanged: popularity stays 0.0, last_checked_at stays 1000, and the instance error stays ('boom', 5, 'video').</expected>\n<wrong_implementation>Today's code turns the failed fetch into `{}` and still writes. The run showed urlopen-urlerror and status-404 red here, with popularity 0.0\u21920.0402\u2026, last_checked_at 1000\u21921790556048333 and the instance error cleared to (None, None, None). A parse guard that catches only JSONDecodeError still raises on bad UTF-8, and one that lets a list through raises AttributeError. In the run, not-json, bad-utf8 and json-list all raised out of `handle_video_request` (JSONDecodeError at video.py:86, UnicodeDecodeError at :85, AttributeError at :167).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:150 \u2014 the failure response answers the stored values: title, description, views, tags, category, language label, duration, thumbnailUrl and channelName</assertion>\n<expected>{\"title\": \"Old title\", \"description\": \"Old desc\", \"views\": 1, \"tags\": [\"old\"], \"category\": \"Music\", \"language\": \"French\", \"duration\": 10, \"thumbnailUrl\": \"https://peer.example/old.jpg\", \"channelName\": \"Old Chan\"}</expected>\n<wrong_implementation>A handler that never adds the new keys reads \"MISSING\" for tags, duration and thumbnailUrl; today's response has no such keys. A failure path that answers nulls or blanks instead of the DB row reads None or \"\" for those fields.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:151 \u2014 the failure response `nsfw` is exactly False</assertion>\n<expected>False (the seeded 0, converted to a bool)</expected>\n<wrong_implementation>With no nsfw key the check reads \"MISSING\". If the raw DB integer passes through it reads 0, and the `is` check rejects that.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:167 \u2014 after a full SOURCE payload, served as JSON through the real `fetch_instance_json`, the whole videos row equals the seed with only the source fields replaced; popularity and last_checked_at are left free</assertion>\n<expected>title \"New title\", description \"New desc\", channel_name \"New Chan\", views 50, likes 5, dislikes 1, category \"Science & Technology\", language \"en\", nsfw 1, duration 321, thumbnail_url \"https://peer.example/static/thumbnails/new.jpg\"; every other column is as seeded</expected>\n<wrong_implementation>An UPDATE that does not extend its SET list leaves the new columns alone. The run showed today's code keeping language 'fr', duration 10 and thumbnail_url 'https://peer.example/old.jpg'. Storing the label instead of the code would give language \"English\". Leaving `thumbnailPath` relative would store \"/static/thumbnails/new.jpg\".</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:172 \u2014 the success response answers the same merged values</assertion>\n<expected>title \"New title\", description \"New desc\", views 50, likes 5, dislikes 1, tags [\"alpha\", \"beta\"], category \"Science & Technology\", language \"English\", duration 321, thumbnailUrl \"https://peer.example/static/thumbnails/new.jpg\", channelName \"New Chan\", subscribersCount 9</expected>\n<wrong_implementation>A response built from the pre-write DB row, or one without the new keys, gives stale values or \"MISSING\" for tags, duration and thumbnailUrl. A response that echoes the stored language code gives \"en\" instead of \"English\".</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:194 \u2014 for a partial payload in two forms, `{\"views\": 77}` and one with a blank name and description, null tags, category, nsfw, duration and thumbnailPath, and `language {\"id\": null}`, the row equals the seed with only views 77 changed; the control at :193 first proves the write ran</assertion>\n<expected>Only views changes, to 77. tags_json stays '[\"old\"]', category 'Music', language 'fr', nsfw 0, duration 10 and thumbnail_url the old URL; popularity and last_checked_at are left free.</expected>\n<wrong_implementation>If the merge writes `resolve_asset_url`'s \"\" for a missing thumbnail, thumbnail_url reads \"\". If null tags are turned into \"[]\", tags_json reads \"[]\". A null language id stored as-is gives language NULL, and writing a blank title or description gives \"  \" or \"\". Today's code passes this line only because it never writes those columns; its red comes at :196.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:196 \u2014 the partial-payload response answers the kept DB values, with views 77</assertion>\n<expected>{\"title\": \"Old title\", \"description\": \"Old desc\", \"views\": 77, \"tags\": [\"old\"], \"category\": \"Music\", \"language\": \"French\", \"duration\": 10, \"thumbnailUrl\": \"https://peer.example/old.jpg\", \"channelName\": \"Old Chan\"}</expected>\n<wrong_implementation>A response that uses the source value whenever the key is present answers None or \"\" for the absent fields. Today's code answers \"MISSING\" for tags, duration and thumbnailUrl, and the run showed exactly those three keys differing.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:206 and :207 \u2014 `tags: []` stores exactly \"[]\" and answers []</assertion>\n<expected>tags_json == \"[]\" and response tags == []</expected>\n<wrong_implementation>The current `to_tags_json` turns an empty list into None, so the stored value is kept. The run showed '[\"old\"]' at :206. A response parser that falls back to the DB when the list is empty would answer [\"old\"].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:219 and :221 \u2014 the raw bodies `{\"name\": \"Fresh title\", \"duration\": 42}` and `{}`, read through the real `fetch_instance_json`, both count as a success. The stored (title, duration, last_checked_at moved) and the answered (title, duration) follow the merge: source values where present, DB values where absent</assertion>\n<expected>object: (\"Fresh title\", 42, True) stored and (\"Fresh title\", 42) answered; empty-object: (\"Old title\", 10, True) stored and (\"Old title\", 10) answered</expected>\n<wrong_implementation>A success guard written as `if not detail` treats `{}` as a failure and writes nothing, so last_checked_at stays 1000 and :219 reads (\"Old title\", 10, False). Today's code never writes duration: the run showed ('Fresh title', 10, True) at :219 for the object case, and ('Old title', 'MISSING') at :221 for the empty object.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:233 and :235 \u2014 two requests are made, and the source renames the video and changes its tags in between. Both responses and the final row carry the source values of their own request</assertion>\n<expected>responses [(\"New title\", [\"alpha\", \"beta\"]), (\"Renamed\", [\"gamma\"])]; stored (\"Renamed\", [\"gamma\"])</expected>\n<wrong_implementation>A handler that answers from the row it read before writing gives the first request's values on the second response. Today's code has no tags key, and the run showed ('New title', 'MISSING') at index 0 on :233.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, before the rewrite. The docstring says a JSON object body \"counts as a success\", but test_object_body_counts_as_success only checked title and last_checked_at. Both are already true today, so the test measured nothing about this phase, and the first run had it green in both cases. Rewrite: the object body now carries duration 42, and the test asserts that the stored and answered duration follow the merge (42 for the object, the DB's 10 for `{}`). After the rewrite every docstring bullet has an assertion behind it. Failure: :149/:150/:151 across five causes. Full success: :163\u2013:173. Absent/null/blank payloads: :194/:196/:197. `tags: []`: :206/:207. Object body including `{}`: :219\u2013:221. Source change: :233/:235.\n2. Absence only: no. :149 (nothing changed) is backed by the control at :147, which proves the fake urlopen was called with (VIDEO_URL, 8). It is also backed by :142, which proves the seeded error is non-NULL so the comparison has something to preserve. :194 and :206 (fields kept) are backed by :193, which proves the write ran.\n3. Echoed literal: no. popularity and last_checked_at on :167/:194 are deliberately left free, not asserted. last_checked_at is checked on its own at :165/:193, and popularity is derived, not a source field. Every other expected value is a literal from the seed or from SOURCE. The production lines whose deletion turns each row red: the new SET columns (:167), the `tags`/`duration`/`thumbnailUrl`/`nsfw`/label response keys (:150/:172/:196/:221/:233), the `is None` success guard (:149), the ValueError and non-dict parse guard in `fetch_instance_json` (:149 for not-json, bad-utf8 and json-list), the `or None` on thumbnail_url and the null/blank handling (:194), and `to_tags_json` returning \"[]\" (:206).\n4. One value: no. The failure claim is read at five inputs. The keep rule is read at two payload shapes and against a full success. The object-body rule is read at a non-empty object and at `{}`. The source-change rule is read over two successive requests. No value is pinned against a sibling from the same source; the expected values are independent literals.\n5. The double: yes, before the rewrite. `_serve` replaced `video.fetch_instance_json`, which is project-owned code this phase changes (the parse guard and the non-dict rule). Rewrite: the fetch_instance_json stub is gone. Every test now replaces only `video.urlopen`, the stdlib network boundary, with a fake keyed by URL path. Dicts are served as JSON bytes, bytes are served raw, exceptions are raised, a `_FakeResponse` is returned as is, and an unlisted path raises URLError. The real `fetch_instance_json` therefore parses every body. The old `stub-none` case (the stub returning None) became `status-404`: a 404 whose body is `{}`, which the real code must reject on status. The only other double is `respond_json`, the HTTP write boundary.\n6. It collects: yes. All imports resolve and the run collected and executed 12 tests (5 failure, 1 success, 2 partial, 1 empty-tags, 2 object-body, 1 two-request), which matches what I wrote. `req.full_url` exists on urllib's Request: the call records carried the full URL, and the control at :147 passed in the urlerror and status-404 cases. The collect-only output above prints \"no tests\" with exit 0. That is this runner's collect-only summary, not a collection failure, since the real run collected 12 items.\n7. Observed, not predicted: the premises were observed. From the earlier probe: the seeded row shape, today's response keys, the fake-urlopen call shape (url, 8), and today's write-on-failure. From this run: the real `fetch_instance_json` reads a JSON-encoded dict served by the new fake, since the success and partial cases reached their data assertions. A 404 `_FakeResponse` reaches the `resp.status != 200` branch; status-404 got past :147 and failed at :149 with the same write-on-failure diff as urlerror. The expected values for behaviour not yet built (duration 42/321 stored, \"[]\", thumbnailUrl, the language label) cannot be observed before the phase exists. They are taken from R2/R5 and the phase plan, not presented as observations. The labels \"English\"/\"French\" were observed through the probe's `language_label` calls, and today's response already answered 'French'/'Music'.\n8. Red, not green: yes. The final run gave \"12 failed\" with [exit status 1]. The first run had \"10 failed, 2 passed\" (both test_object_body_counts_as_success cases green); after the rewrite in 1, neither is green.\n9. Red for the right reason: yes, in the final run. In the first run there was one control failure: :245 (the first-response control in test_second_request_reflects_source_change) failed on `('New title', 'MISSING') != ('New title', ['alpha', 'beta'])`, so the C2 assertion after it never ran. Rewrite: that control is merged into the single C2 assertion at :233. In the final run each red is at a clause assertion or at production raising. urlopen-urlerror and status-404 fail at :149 (`At index 0 diff: \u2026 0.0402\u2026, 1790556048333 \u2026 != \u2026 0.0, 1000 \u2026`, and the instances tuple went (None, None, None) against (\u2026, 5, 'video')). not-json fails with JSONDecodeError at video.py:86, bad-utf8 with UnicodeDecodeError at video.py:85, and json-list with AttributeError \"'list' object has no attribute 'get'\" at video.py:167. All three raise out of `handle_video_request` at test line :144, after the fake urlopen served the body; that crash is the missing parse guard C1 requires, not a harness defect. Success fails at :167 (`{'language': 'fr'} != {'language': 'en'}`, `{'duration': 10} != {'duration': 321}`, and thumbnail old != new). Both partial cases fail at :196 (tags, duration and thumbnailUrl 'MISSING'). Empty tags fails at :206 (`'[\"old\"]' == '[]'`). Object fails at :219 (`('Fresh title', 10, True) == ('Fresh title', 42, True)`). Empty-object fails at :221 (`('Old title', 'MISSING') == ('Old title', 10)`). The source change fails at :233 (index 0 `('New title', 'MISSING')`). Every control (:142, :147, :193, :217, :232) that the run reached passed.\n10. Observed expected output: the run does not contradict any row's `expected` column. Each `wrong_implementation` quotes the value this run actually showed under today's code. The `expected` values are the post-phase values; the run cannot show them yet, and they come from the requirements, as stated in 7.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `engine/server/api/handlers/video.py`\n- **`fetch_video_row`** now also selects `v.duration` and `v.thumbnail_url`, so a failed fetch can still answer them from the DB. `v.language` was already selected in phase 2.\n- **`fetch_instance_json`** returns a `dict` or `None`. It still calls `urlopen(req, timeout=8)`, still catches `HTTPError`/`URLError`/`TimeoutError`, and a non-200 status still returns `None`. Two more cases return `None` and log at info:\n  - a `ValueError` (this covers both `UnicodeDecodeError` and `JSONDecodeError`);\n  - a parsed body that is not a `dict`.\n  The `# pragma: no cover` on the except line is gone.\n- **New helpers:**\n  - `pick_present(value, fallback)`: returns the source value unless it is None, otherwise the DB value.\n  - `id_text`: turns an int (never a bool) or a non-empty trimmed string into text.\n  - `tags_from_json`: parses the stored `tags_json` into its string tags. Null, empty, invalid or non-list values give `[]`.\n  - `extract_language`: returns an object's `id`, or a plain non-empty string, through `pick_text`. A null id gives `None`.\n- **Changed helpers:**\n  - `to_tags_json` returns `\"[]\"` for an empty list, and `None` only when the value is not a list. It writes raw UTF-8 (`ensure_ascii=False`) to match the crawler, as the settled draft decided.\n  - `extract_category` falls back to the id as text when there is no label. Plain values go through `id_text`, so `\"\"` or whitespace keeps the DB value.\n- **`fetch_instance_video_dynamic`** returns `None` exactly when the detail fetch gives no dict. This is the single success signal. `account` and `channel` are guarded with `isinstance(dict)`. The function now also returns:\n  - `language`, from `extract_language`;\n  - `duration`, from `pick_number`;\n  - `thumbnail_url`, from `resolve_asset_url(thumbnailUrl or thumbnailPath)`, with `\"\"` mapped to `None` so a missing thumbnail never blanks the stored one.\n  The channel-detail fallback is unchanged, so if that second fetch fails, the stored follower count is kept.\n- **`handle_video_request`**\n  - If there is no host, or the fetch fails, `dynamic` is `None` and `source = {}`.\n  - One merged value set (source value where present, else the DB value) now covers title, description, stats, channel, tags_json, category, language, nsfw, duration and thumbnail_url. The same set feeds the response and the UPDATE.\n  - The response keeps all 18 original keys. `accountAvatarUrl` now reads from `source`. Four keys are added: `tags` (a list), `nsfw` (a bool or null), `duration` and `thumbnailUrl`. `language` now labels the merged code rather than the DB row's code.\n  - The write guard is now `dynamic is not None`, which checks identity rather than truthiness. On failure no `videos`, `channels` or `instances` statement runs. A `{}` body still counts as a success.\n  - The `videos` UPDATE also sets `language`, `duration` and `thumbnail_url`. The `channels` UPDATE, the `instances.last_error*` reset, the transaction and the `OperationalError` catch are unchanged.\n\n### `tests/active/test_video_handler.py`\nNot touched. The phase lists it as EDITED, but it does not exist in this worktree. This phase's checkpoint lives in `tests/tmp/test_10_video_metadata_completeness_phase3.py`, and I did not edit that file either. Presumably it is moved into `tests/active` at harvest.\n\nNot run: I did not execute the checkpoint myself. I checked it by reading each test's cases against the code. The phase 2 checkpoint (`test_refresh_stores_raw_codes`, where an id-only category is now stored as `\"15\"` rather than keeping the DB value) should also stay green under the new rules, but that too is from reading, not from a run.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_10_video_metadata_completeness_phase4.py": "<assertions>\ntests/tmp/test_10_video_metadata_completeness_phase4.py:108 \u2014 control: the page requested `/api/video` from the stubbed fetch (every case, via `_page`)\ntests/tmp/test_10_video_metadata_completeness_phase4.py:109 \u2014 control: `video-title` shows the fixture body's title, so `loadVideo` settled on the server body the taxonomy block reads (every case)\ntests/tmp/test_10_video_metadata_completeness_phase4.py:116 \u2014 the `video-category` item starts hidden and is not hidden after load \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:117 \u2014 `video-category-value` text is \"Science & Technology\" \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:118 \u2014 the `video-language` item starts hidden and is not hidden after load \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:119 \u2014 `video-language-value` text is \"English\" \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:120 \u2014 `video-tags` children are exactly two element nodes with class `tag-chip` whose text is \"alpha\" then \"beta\", in that order (markup set through innerHTML shows up as a text-less non-chip, so a chip that is not text fails) \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:126 \u2014 for an empty category, the `video-category` item starts visible and is hidden after load \u2014 C2\ntests/tmp/test_10_video_metadata_completeness_phase4.py:127 \u2014 for an empty language, the `video-language` item starts visible and is hidden after load \u2014 C2\ntests/tmp/test_10_video_metadata_completeness_phase4.py:128 \u2014 for `tags: []`, the only child of `video-tags` reads \"No tags\" (a child element or text set through textContent both count) \u2014 C2\ntests/tmp/test_10_video_metadata_completeness_phase4.py:134 \u2014 edge case with a category, an empty language and one tag: the category item starts hidden and is not hidden after load \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:135 \u2014 edge case: `video-category-value` text is \"Music\" \u2014 C1\ntests/tmp/test_10_video_metadata_completeness_phase4.py:136 \u2014 edge case: the language item is hidden on its own, not tied to the category \u2014 C2\ntests/tmp/test_10_video_metadata_completeness_phase4.py:137 \u2014 edge case: `video-tags` holds exactly one `tag-chip` whose text is \"solo\" (checks the count is not off by one) \u2014 C1\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/probe_10_phase4_taxonomy.py\", \"-s\"]. The probe loads the checkpoint's RUNNER, BASE and `_page`, bundles `pages/video-page/index.ts` with the checkpoint's esbuild flags, and runs all three fixture bodies against three things: the current page, a hand-written correct renderer (RIGHT) and a hand-written wrong one (WRONG). What it printed:\n- esbuild with `--loader:.css=empty --platform=node` exits 0 and writes a 44.1kb bundle, so the `video.css` import bundles to nothing.\n- CURRENT page, every case: requested = ['/api/video', '/recommendations', '/api/v1/config']; video-title text = 'Taxonomy fixture title'. Both controls hold on today's code. The four taxonomy ids report {text: None, hidden: None} and tags = [] because the page never looks them up. So every taxonomy assertion is red today, and it is red because the block is missing, not because the harness broke.\n- RIGHT (sets `hidden = !value`, `replaceChildren` with `createElement` `tag-chip` spans, `textContent = \"No tags\"`), case 1: category/language hidden False with values 'Science & Technology' and 'English'; tags [{alpha, chip True}, {beta, chip True}].\n- RIGHT, case 2: category and language hidden True; tags [{'No tags', chip False}].\n- RIGHT, case 3: category hidden False with value 'Music'; language hidden True; tags [{solo, chip True}].\n- So every assertion passes against a correct renderer, and a `textContent = \"No tags\"` shows up as the one child.\n- WRONG (category always un-hidden, language hidden by the category's emptiness, tags through innerHTML), case 1: tags [{'', chip False}], so line 120 fails.\n- WRONG, case 2: category hidden False, so line 126 fails, and tags [{'', False}], so line 128 fails.\n- WRONG, case 3: language hidden False, so line 136 fails, and line 137 fails.\nI have no delete tool, so `tests/tmp/probe_10_phase4_taxonomy.py` is still on disk and should be removed (it ends in `assert False`).\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_10_video_metadata_completeness_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase4.py:116, :118, :134 assert that `video-category` and `video-language` are `hidden is False` after load. Both items start hidden (`initially_hidden=ITEMS`, and `[\"video-category\"]` in case 3). Lines :117, :119 and :135 assert that the `video-category-value` and `video-language-value` text is \"Science & Technology\", \"English\" and \"Music\". Line :120 asserts that the `video-tags` children equal `[{\"text\": \"alpha\", \"chip\": True}, {\"text\": \"beta\", \"chip\": True}]`, and :137 that they equal `[{\"text\": \"solo\", \"chip\": True}]`.</assertion>\n<expected>This is what the probe's RIGHT renderer produced when run through this exact RUNNER and `_page`, not a prediction. The RIGHT renderer sets `hidden = !value`, sets `textContent` on the value element, and calls `replaceChildren` with `createElement` + `className = \"tag-chip\"` + `textContent` chips, which is the plan's `setTaxonomyItem`/`renderTaxonomy` shape. Case 1 reported video-category {hidden: False}, video-category-value {text: 'Science & Technology'}, video-language {hidden: False}, video-language-value {text: 'English'}, and tags [{'text': 'alpha', 'chip': True}, {'text': 'beta', 'chip': True}]. Case 3 reported video-category {hidden: False}, value 'Music', and tags [{'text': 'solo', 'chip': True}]. On today's page each of these ids reads {text: None, hidden: None} and tags reads [].</expected>\n<wrong_implementation>Wrong implementation 1: the chips are built with `innerHTML = tags.map(t => `<span class=\"tag-chip\">${t}</span>`).join(\"\")`, markup instead of text chips. The probe's WRONG run shows tags [{'text': '', 'chip': False}], so :120 and :137 go red. Wrong implementation 2: a renderer that never clears the item's `hidden`, such as the HTML's `hidden` attribute left in place. The item then stays at its starting hidden=True, so :116, :118 and :134 go red. Wrong implementation 3: a renderer that writes the value into the item instead of `*-value`. The value element then reads None or '', so :117, :119 and :135 go red. Wrong implementation 4: an off-by-one or a renderer that drops tags. The list comparison at :137 (length 1) and :120 (length 2, in order) catches both.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_10_video_metadata_completeness_phase4.py:126 and :127 assert that `video-category` and `video-language` are `hidden is True` for a body with `category: \"\"` and `language: \"\"`. Both items start visible (`initially_hidden=[]`). Line :128 asserts that the texts of the `video-tags` children equal `[\"No tags\"]`. Line :136 asserts that `video-language` is `hidden is True` in case 3, where the category is non-empty and starts hidden.</assertion>\n<expected>This is observed from the probe's RIGHT renderer through this RUNNER. Case 2 reported video-category {hidden: True}, video-language {hidden: True}, and tags [{'text': 'No tags', 'chip': False}], so the child texts are ['No tags']. Case 3 reported video-language {hidden: True} while video-category was {hidden: False}. On today's page the ids read hidden None and tags reads [].</expected>\n<wrong_implementation>Wrong implementation 1: category is always shown, e.g. `removeAttribute(\"hidden\")` whatever the value. The probe's WRONG run showed case 2 video-category {hidden: False}, so :126 goes red. Wrong implementation 2: the language item's visibility is keyed on the category's emptiness, a copy-paste slip. WRONG case 3 showed video-language {hidden: False}, so :136 goes red. Case 2 alone cannot tell this apart, because both fields are empty there. Wrong implementation 3: \"No tags\" is written through `innerHTML` as markup. WRONG case 2 showed tags [{'text': '', 'chip': False}], so :128 goes red. Wrong implementation 4: an empty tag list renders nothing. The child texts are then [], so :128 goes red. Because the items start visible, a renderer that never touches `hidden` also fails :126 and :127.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. The docstring makes three claims and each has assertions. Case 1 (values shown, one `tag-chip` per tag, in order, text only) is lines 116\u2013120. Case 2 (both items hidden, only child \"No tags\") is lines 126\u2013128. Case 3 (only language hidden, one chip) is lines 134\u2013137. The docstring also claims each item starts in the opposite visibility to the one expected. The `initially_hidden` argument does that, and the probe showed the stub honours it: RIGHT flipped every item away from its start.\n2. Absence only: no. The `hidden is True` assertions (126, 127, 136) each start from `hidden=False`, so the page has to set them. They are not left over from a code path that never ran. The positive controls at lines 108 and 109 (`/api/video` was requested, and `video-title` reads the fixture title) passed in the run. So `loadVideo` settled on the fixture body before any taxonomy assertion was read.\n3. Echoed literal: no. Expected values are fixture inputs that the page has to route to the right element, and the test does no transformation of its own. The lines whose deletion turns each assertion red are in the planned `renderTaxonomy`/`setTaxonomyItem` (the plan's phase-4 draft; not yet in `index.ts`). Deleting `if (itemEl) itemEl.hidden = !value;` turns 116/118/126/127/134/136 red. Deleting `if (valueEl) valueEl.textContent = value;` turns 117/119/135 red. Deleting `item.textContent = tag;` or `item.className = \"tag-chip\";` turns 120/137 red. Deleting `empty.textContent = \"No tags\";` turns 128 red.\n4. One value: no. The category is read at three bodies (\"Science & Technology\", \"\", \"Music\"), and its visibility at shown/hidden/shown. Language visibility is read at \"English\" (shown), \"\" with an empty category (hidden) and \"\" with a non-empty category (hidden), which separates it from the category. Tags are read at 2, 0 and 1 elements. Nothing is pinned against a sibling from the same source: each expected value is a literal from the case's own body.\n5. The double: no owned module is doubled. The page module `pages/video-page/index.ts` and every project module it imports (`data/videos`, `data/reactions`, `data/profile`, `data/blocks`, `utils/safe-url`, `components/key-rejected`) are bundled for real by esbuild. The stubs cover only what node lacks: `document`/elements, `window.location`, the storages, and `fetch` at the HTTP boundary to the backend. That boundary is the severed layer the plan's checkpoint names.\n6. It collects: yes. The `--collect-only` summary prints \"no tests\" in that mode, but the real run reported \"collected 3 items\". That matches the three test functions. Imports are stdlib plus pytest. `_page(bundle, body, initially_hidden)` matches its signature at every call. `ESBUILD` exists: the probe's esbuild run exited 0 and wrote a 44.1kb bundle. The ids `video-category`, `video-category-value`, `video-language`, `video-language-value`, `video-tags` and the class `tag-chip` are the ones the plan's draft uses (plan lines 1119\u20131123, 1174).\n7. Observed, not predicted: yes. Every expected shape comes from the probe run of `tests/tmp/probe_10_phase4_taxonomy.py`, which I re-ran this turn. It feeds all three bodies through this file's RUNNER and `_page` against the current page, a correct stand-in renderer (RIGHT) and a wrong one (WRONG). RIGHT printed exactly the values each assertion expects, including `hidden` True/False, value text, `[{'text': 'alpha', 'chip': True}, {'text': 'beta', 'chip': True}]` and `[{'text': 'No tags', 'chip': False}]`. WRONG went red at 120, 126, 128, 136 and 137. One thing I could not observe: whether the real implementation will use `.hidden` or `setAttribute(\"hidden\")` rather than a CSS class. The stub records both of the first two, and the plan specifies `itemEl.hidden = !value`. It will be confirmed when the implementation runs against this test.\nNo yes answers to 1\u20137, so nothing was rewritten.\n8. Red, not green: yes, it fails. `ValidateTests [\"tests/tmp/test_10_video_metadata_completeness_phase4.py\"]` reported \"3 failed\", exit status 1, and `tests/last_test_output.txt` shows \"collected 3 items \u2026 FFF\".\n9. Red for the right reason: yes. In all three tests the controls at lines 108 and 109 passed: the failure dict shows `'requested': ['/api/video', '/recommendations', '/api/v1/config']` and `'video-title': {'text': 'Taxonomy fixture title', \u2026}`. The first judging assertion then failed on a missing taxonomy lookup. Test 1 failed at line 116 with \"assert None is False\". Test 2 failed at line 126 with \"assert None is True\". Test 3 failed at line 134 with \"assert None is False\". The dict shows `'video-category': {'text': None, 'hidden': None}`: today's `index.ts` never calls `getElementById(\"video-category\")`, so the element was never created. That is the missing phase, not a harness defect.\n10. Observed expected output: yes. Every row's `expected` quotes the probe's RIGHT output from this turn's run. The checkpoint run itself showed `{'text': None, 'hidden': None}` for each taxonomy id, as the probe's CURRENT lines had. Nothing in either run contradicted an expected value. Housekeeping: `tests/tmp/probe_10_phase4_taxonomy.py` still has to be deleted, and I have no delete tool. It ends in `assert False`, so remove it before any run over `tests/tmp`.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### client/frontend/src/pages/video-page/index.ts\n- Added lookups for the new elements: `video-category`, `video-category-value`, `video-language`, `video-language-value` and `video-tags`.\n- `VideoMetadata` has three new fields: `category?: string`, `language?: string` and `tags?: string[]`.\n- `fetchVideoMetadataFromServer` reads `category` and `language` from the `/api/video` body, and uses `\"\"` when either is missing. It reads `tags` only if it is an array, and keeps only the string entries; otherwise it uses `[]`.\n- `loadVideo` fills in the block using a new helper, `renderTaxonomyItem(itemEl, valueEl, value)`. It hides the item when the value is empty and sets the value as text. The tag list gets one `<span class=\"tag-chip\">` per tag through `replaceChildren`, with each chip's text set as text. With no tags, the list's text is set to \"No tags\". Nothing goes through `innerHTML`, because tags come from remote instances.\n- Not done: the PeerTube instance fallback (`fetchVideoMetadataFromInstance`) does not map `category`, `language` or `tags`. Phase 4 is limited to `/api/video`. When the page falls back to the instance, both items stay hidden and the tag list reads \"No tags\".\n\n### client/frontend/video-page.html\n- Added `<dl id=\"video-taxonomy\" class=\"video-taxonomy\">` between `video-meta-row` and `video-description`. It has three `taxonomy-item` rows:\n  - Category: `#video-category` holding `dd#video-category-value`\n  - Language: `#video-language` holding `dd#video-language-value`\n  - Tags: `dd#video-tags.tag-list`\n- The category and language rows start `hidden`, so they don't show as empty labels before the metadata arrives.\n\n### client/frontend/src/video.css\n- New rules for `.video-taxonomy`, `.taxonomy-item` and its `dt`/`dd`, `.tag-list` and `.tag-chip`. The chips are pill-shaped like the existing `.instance-meta` chips.\n- Added `.taxonomy-item[hidden] { display: none; }`. Without it, the flex display on `.taxonomy-item` would override the `hidden` attribute.\n\n### client/frontend/dist\n- **Not rebuilt.** I have no shell, so I couldn't run `npm run build` or delete the old hashed `video-*.js` / `video-*.css` files it replaces. The checkpoint builds its own bundle from `src` with esbuild and doesn't read `dist`, so it isn't affected. As agreed at Step 6, the operator still needs to run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before the merge.\n\n### tests/active/test_frontend_video_taxonomy.py\n- Not created by me. The checkpoint is `tests/tmp/test_10_video_metadata_completeness_phase4.py`, and I assume the workflow moves it to this path. I left it untouched.\n\n### Observation\n- A probe (`tests/tmp/probe_10_phase4_impl.py`) built the edited `index.ts` with the checkpoint's own esbuild command and ran it under the checkpoint's runner. Results:\n  - **Body 1:** category and language showing with \"Science & Technology\" and \"English\"; tags `alpha` and `beta` as `tag-chip`s.\n  - **Empty body:** both items hidden; the only child of the tag list is \"No tags\".\n  - **Music body:** only the language item hidden; one `solo` chip.\n- In all three cases the control fields matched: `/api/video` was requested and the title was rendered.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_10_phase4_impl.py - my throwaway probe (see changes). I have no tool that deletes files, so it's still there and needs removing by hand.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone - I read all four phases' production code (schema.sql, db.ts, videos-worker.ts, both dist files, whitelist_migrations.py, sync-whitelist.py, peertube_labels.py, handlers/video.py, video-page.html, index.ts, video.css) and found nothing in this build's changes worth consolidating without changing behaviour, so I edited no file.\n</refactors>\n\n<left_out>\nMerging `migrateVideosLanguage` into `migrateVideos` (db.ts), and `migrate_videos_language` into `migrate_videos_schema` (whitelist_migrations.py): left out because both paths are needed. The rebuild only fires when the error columns are missing, so a table that already has them but lacks `language` can only get it from the ALTER. Folding them together would change which DBs get migrated.\nReading `extract_language`/`extractLanguage` and `category_label`/`language_label` from one shared place: left out because they live on opposite sides of the TS/Python boundary, and each already matches the style of its file.\nPulling the tag-chip rendering in `loadVideo` (index.ts) into its own helper next to `renderTaxonomyItem`: left out because it would be cosmetic only, with one call site and no second user.\nThe pre-existing duplication in videos-worker.ts (`groupByInstance`/`groupByInstanceTags`/`groupByInstanceComments`, `processTagInstance`/`processCommentsInstance`) and the `DEPRECATED_*` migration scaffolding in db.ts: left out because this build did not write them, and changing them would grow the build past what was approved.\nengine/crawler/dist/db.js and dist/videos-worker.js: these are still hand-edited rather than tsc output, and I can't run a shell to rebuild them. The operator should run `cd engine/crawler && npm install && npm run build` and review the dist diff before commit.\nclient/frontend/dist: still not rebuilt (phase 4 had the same limit). The operator should run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before merge.\nThe probes this build left in tests/tmp: probe_10_dist_language.py (emptied), probe_10_phase4_impl.py, probe_10_phase4_taxonomy.py, probe_10_phase3_channels.py, probe_10_phase3_refresh.py, probe_10_phase2_shape.py, probe_10_phase2_labels.py, probe_10_crawl.py and probe_10_language.py. I have no delete tool, so the operator needs to remove them.\nThe step's \"What the pass is measured against\" section reached me as an unfilled `{rat_tail_rules}` placeholder. I measured against the role's rules instead: the build's only deliberate simplification, the stock label lists in peertube_labels.py, already has a `rat-tail:` comment naming the ceiling and the upgrade path.\n</left_out>\n\n<needs_fresh_red>\nnone - mapping category, language and tags in the video page's PeerTube-instance fallback (`fetchVideoMetadataFromInstance`) would be new behaviour, but phase 4 left it out of scope on purpose, so it belongs on the roadmap if wanted, not in this pass.\n</needs_fresh_red>\n\n<observation>\nFrom reading the code (nothing was run, and no file changed): the landed code needs no refactor, and the unbuilt dist output plus the leftover tests/tmp probes are the only loose ends, both for the operator.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"DATA_BUILD.md\" update=\"yes\">\nThe build adds `videos.language` to both producers. Section 1 (crawl) needs a sentence saying the crawler stores each video's PeerTube language code in `videos.language`, and that any crawler command opening an existing `crawl.db` adds the column (`migrateVideosLanguage` in `db.ts`). Section 2 (sync) needs two notes. First, `sync-whitelist.py` refuses a `crawl.db` the crawler has not opened since the change (the superset check). Second, it refuses an existing `whitelist.db` until `migrate-whitelist.py` has added `language` (the exact check). Beside the `migrate-whitelist.py` block (around line 157), add the upgrade order: merge; open or run the crawler once on `crawl.db`; run `migrate-whitelist.py` on every `whitelist.db`, prod included; restart the Engine. Also state that `run-dataset-build.sh` does not migrate on its own, and that `/api/video` refreshes written to `whitelist.db` are replaced by the next sync (`rebuild_content_tables` reloads from `crawl.db`).\n</doc>\n<doc path=\"engine/server/README.md\" update=\"yes\">\nLine 9 reads only \"`/api/video` metadata for the video page\", which no longer describes the route. It should say the following. One fetch of `/api/v1/videos/{id}` from the source instance refreshes the stored title, description, stats, tags, category, language, nsfw, duration and thumbnail. A write happens only when that fetch returns a JSON object. A failed, unreachable or malformed source leaves the DB untouched (`last_checked_at` and `instances.last_error` included), and the response is built from the DB row. The response adds `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Category and language are shown as PeerTube's default labels (`data/peertube_labels.py`), with the raw id or code when no default label exists. The Engine needs a `whitelist.db` migrated with `migrate-whitelist.py` (`language` column), or `/api/video` fails with `no such column: v.language`.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"yes\">\nLine 374-375 says `/api/video` makes live calls per request. Add that the route writes the refreshed metadata back to `whitelist.db` only when the source answers with a valid video object inside the request's statement deadline (5 s by default). A slower source is still answered with fresh values but nothing is stored. Add an upgrade note or a Triage row for this deploy: run `migrate-whitelist.py` on the Engine's `whitelist.db` before restarting the Engine. If that is skipped, every video page silently falls back to direct-instance metadata, the Client proxy logs 502 `ENGINE_PROXY_UNAVAILABLE` on `/api/video`, and the Engine journal shows `no such column: v.language`.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nImplementation-order step 2 (line 142) reads \"feed panel I1 and I2, then I3 \u2026 Landing I1 before any further crawl avoids a second full re-crawl.\" That is out of date: the language capture part of I1 is delivered. The crawler and `/api/video` store the PeerTube language code in `videos.language`, and labels resolve at read time through `engine/server/data/peertube_labels.py`. Rewrite the step to name what remains: label storage only if it is still wanted, the I2 filter, and the I3 backfill. Note that existing rows get a language only from a full re-crawl, since `--new-videos` and INSERT_ONLY merges skip existing rows, or from video-page views in `whitelist.db`, which the next sync discards.\n</doc>\n<doc path=\"docs/project/plans/archive/04-feed-parameter-panel.md\" update=\"yes\">\nI1 (line 19-20) and acceptance item 1 (line 47) specify new `language_id` and `language_label` columns. The `videos` table now already has `language` (code only) in `engine/crawler/schema.sql`, the whitelist schema and the migration, and the crawler already captures it in `toVideoRow`. Record this against I1 so a future I1 build does not add a duplicate column: the column is `language` rather than `language_id`, the capture is delivered, and labels come from `engine/server/data/peertube_labels.py` at read time. Line 40 (backfill) and R1 (sparse data) stay valid.\n</doc>\n<doc path=\"docs/project/plans/18-english-subtitles.md\" update=\"yes\">\nThree statements are now false. Line 20 says the `videos` table \"stores no language\". Line 43 lists \"adding a `language` column to the crawl\" as out of scope, which is now done by another build. Line 90 says there is \"no language column to select by\". Update them to say that `videos.language` holds the PeerTube language code, filled by the crawler for newly crawled videos and by `/api/video` views. Coverage for existing rows is sparse until a re-crawl or backfill.\n</doc>\n<doc path=\"docs/project/issues/10-video-metadata-completeness.md\" update=\"yes\">\nThis is the issue the build delivers, so it is done at harvest on main. Set `Status: enhancement, complete` and append a delivery comment. The comment records the accepted limits:\n- labels come from PeerTube defaults only (plugin or renamed entries show the raw id or code);\n- PeerTube's unset category shows as \"Unknown\";\n- language and description removals at the source do not propagate (null or empty keeps the DB value);\n- persistence is best-effort under the 5 s statement deadline;\n- refreshes in `whitelist.db` are lost at the next sync;\n- the video page's instance-direct fallback (`fetchVideoMetadataFromInstance`) does not show category, language or tags, which diverges from R6.\n\nThen move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/issues/14-collapsible-description.md\" update=\"no\">\nNothing it claims is false. It describes the `video-description` behaviour, which this build did not change. The new `video-taxonomy` block between `video-meta-row` and `video-description` only affects merges: expect a conflict at harvest when both touch the adjacent markup, CSS and `loadVideo` fill code. That is a note for the merge, not a document edit.\n</doc>\n<doc path=\"README.md\" update=\"no\">\nIt mentions `/api/video` only as a public route (line 46-48) and as a smoke check expecting 200 through the Client proxy (line 134). Both are still true once the whitelist DB is migrated. It says nothing about what the route returns or refreshes.\n</doc>\n<doc path=\"client/README.md\" update=\"no\">\nIt lists `/api/video` only as a read-gateway route (line 37). The proxy still passes the body through unchanged, so the line stays accurate.\n</doc>\n<doc path=\"client/frontend/README.md\" update=\"no\">\nIt says the frontend fetches `/api/video` and renders the video page (lines 8-9), without listing which metadata the page shows. Nothing there is made false by the new taxonomy block.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone - there is no `docs/project/adr/` directory or any ADR file in this worktree, and no `docs/wiki/` either, so no ADR covers the area this build touched.\n</adr_conflicts>",
    "step_9_i2_update:DATA_BUILD.md": "<changes>\nDATA_BUILD.md: added `videos.language` to the crawl and sync sections, plus the schema checks and upgrade order for sync.\n\n- **Section 1, Video crawl:** the crawler stores each video's PeerTube language code in `videos.language`, and stores NULL when the payload has no language or a null id. Any crawler command that opens an existing `crawl.db` adds the column (`migrateVideosLanguage` in `db.ts`). Rows already in the table stay NULL until a video crawl without `--new-videos` visits them again.\n- **Section 2, sync:** a new list of the checks `sync-whitelist.py` runs before copying:\n  - the superset check refuses a `crawl.db` that no crawler command has opened since the change;\n  - the exact check (schema plus `popularity`) refuses an outdated existing `whitelist.db` and points to `migrate-whitelist.py`;\n  - a new `whitelist.db` is created with the current schema.\n- **Next to the `migrate-whitelist.py` block:**\n  - The migration only adds columns: rows, `videos_fts` and its triggers are left alone, and running it again does nothing.\n  - `scripts/run-dataset-build.sh` does not migrate on its own.\n  - The upgrade order: merge; run the crawler once on `crawl.db`; migrate every `whitelist.db`, prod included; restart the Engine. What an unmigrated DB does to `/api/video` is covered in `engine/server/README.md`, and this document points there.\n  - `/api/video` refreshes are lost at the next sync, because `rebuild_content_tables` deletes `videos` and reloads it from `crawl.db`.\n\nChecked against the code: `applyBaseSchema` in `db.ts`, `ensure_schema_compatibility` and `rebuild_content_tables` in `sync-whitelist.py`, the `language` ALTER in `whitelist_migrations.py`, `migrate-whitelist.py` calling `migrate_whitelist_schema`, and `scripts/run-dataset-build.sh`, which only calls `sync-whitelist.py`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/README.md": "<changes>\nI rewrote the `/api/video` bullet in `engine/server/README.md` so it describes what the route does now: it refreshes from the source instance, writes to the DB only when the fetch succeeds, returns six new keys, shows category and language as labels, and needs the `language` migration.\n\nI checked it against `engine/server/api/handlers/video.py`. The bullet now says:\n- Each request fetches `/api/v1/videos/{id}` and refreshes the stored title, description, stats, tags, category, language, nsfw, duration and thumbnail. A field the source leaves absent, null or invalid keeps its DB value.\n- The DB is written only when the fetch returns a JSON object. If the source fails, can't be reached or sends a malformed body, nothing is written (including `last_checked_at` and `instances.last_error`) and the response is built from the DB row.\n- The response adds `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`, with their types.\n- Category and language are stored as ids and codes but returned as PeerTube's default labels from `data/peertube_labels.py`, or as the raw value when there is no default label.\n- The route needs a `whitelist.db` migrated with `db/jobs/migrate-whitelist.py`. Without that, requests fail with `no such column: v.language`. The upgrade order is not repeated here; the bullet points to `DATA_BUILD.md`, which owns it.\n\nI left out the 5 s statement deadline because `DEPLOYMENT.md` owns it. I also didn't give a status code for the unmigrated-DB failure: the handler doesn't catch that error, so the bullet names only the error text.\n\n**Open point:** the intro line still calls the Engine a \"Read-only Engine API\", but `/api/video` writes to `whitelist.db`. I didn't change that line because the triage didn't ask for it.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:DEPLOYMENT.md": "<changes>\nDEPLOYMENT.md: `/api/video` write-back conditions, a whitelist migration note, and a Triage row for an unmigrated `whitelist.db`\n\n- **Section 1 (Prepare the database):** new paragraph. An existing `whitelist.db` must be migrated with `migrate-whitelist.py` before the Engine starts on newer code, or `/api/video` fails. It points to Triage for the symptom and to `DATA_BUILD.md` for the upgrade order, without repeating the steps.\n- **Section 6, Firewall:** the \"Outbound 443\" paragraph is now one line, and a new paragraph follows it:\n  - `/api/video` writes refreshed metadata back to `whitelist.db` only when the source answers with a valid video object.\n  - The write shares the request's statement deadline (5 s by default, `DEFAULT_STATEMENT_TIMEOUT_SECONDS`), and time spent waiting on the source counts against it.\n  - When a slow source uses up the deadline, the page still gets fresh values, the write can be interrupted, and the Engine logs `[video] failed to persist dynamic metadata`.\n- **Section 2, Triage:** new row for a `whitelist.db` that was not migrated. Symptom: video pages lose category, language and tags; the Client logs `engine.proxy` 502 on `/api/video`; the Engine journal shows `no such column: v.language`. The page falls back to reading the source instance directly. Fix: run `migrate-whitelist.py`, then restart the Engine.\n\n**Two places where the doc is worded differently from the checklist, based on the code:**\n- **Deadline wording.** The checklist said a slower source means \"nothing is stored\". The deadline (`data/db.py`) works through SQLite's progress handler, which only checks every 10,000 instructions. So I wrote that the write *can be* interrupted, and named the log line the handler writes when that happens (`video.py`, `except sqlite3.OperationalError`).\n- **502 code not named.** The checklist named `ENGINE_PROXY_UNAVAILABLE`. On a missing column, `do_GET` re-raises the non-interrupt `OperationalError` and the Engine closes the connection with no response. urllib does not wrap the resulting `RemoteDisconnected` in `URLError`, so the Client's proxy should land in its generic `except Exception` branch: `ENGINE_PROXY_FAILURE`, ERROR \"proxy request exception\". This comes from reading the code, not from a run, so the row says only \"`engine.proxy` 502\" and does not name a code.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nroadmap.md: rewrote Implementation-order step 2 (Language) around what remains now that language capture is in, and fixed the stale feed-panel plan path.\n\n- **Step 2** keeps three items and drops the old \"land I1 before any further crawl\" constraint:\n  - I1's remainder: stored labels, only if still wanted. The step also says that `videos.language` already holds the PeerTube language code, filled by the crawler and by `/api/video`, and that labels are looked up at read time through `engine/server/data/peertube_labels.py`.\n  - I2: the filter.\n  - I3: the backfill.\n- **How existing rows get a language:** only from a full re-crawl, because `--new-videos` and the `INSERT_ONLY` videos merge skip rows that already exist. Video-page views also set it, but they write to `whitelist.db` and the next sync discards that. The sync behaviour is pointed at `DATA_BUILD.md` rather than repeated.\n- **Code checked:** `merge_rules.json` has videos as `INSERT_ONLY`; `updater-worker.py` uses `--new-videos`; `toVideoRow` sets `language`; `handlers/video.py` writes `language`.\n- **Path fix (in this same file):** the M4 line F4-M4 linked `docs/project/plans/04-feed-parameter-panel.md`, but that file is at `docs/project/plans/archive/04-feed-parameter-panel.md`. The link now points there.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/archive/04-feed-parameter-panel.md": "<changes>\nRecorded in the plan that I1's language column and crawler capture already exist, as `language` (the code only, no label column), so a later I1 build won't add `language_id`/`language_label` twice.\n\nI checked each claim against the code before writing it: `schema.sql`, `sync-whitelist.py`, `migrate_videos_language` in `whitelist_migrations.py`, `extractLanguage` and `extractCategory` in `videos-worker.ts`, `extract_language` in `handlers/video.py`, and `data/peertube_labels.py`.\n\n- **Status line:** says I1's column and capture are delivered, points to `docs/project/issues/archive/10-video-metadata-completeness.md` (where that issue will sit after harvest), and refers to C1 for the details.\n- **C1:** the two bullets that asked for `language_id`/`language_label` are now one \"Delivered: column and capture\" bullet. It covers:\n  - the nullable `language TEXT` column holding the PeerTube code, and the three places that create it;\n  - `toVideoRow`/`extractLanguage` filling it, and the shape of PeerTube's `{id, label}` payload;\n  - no label column, because labels resolve when read through `engine/server/data/peertube_labels.py`;\n  - an explicit line that I1 adds no `language_id` or `language_label` column.\n\n  I dropped \"lowercase\" because codes like `zh-Hans` are stored as they come.\n- **Acceptance 1\u20132:** now name the `language` column, and each is marked as met by what was delivered.\n- **Consistency constraints:** the bullet that put the normalisation helper in `host-filters.ts` was wrong. It now names `extractLanguage` in `videos-worker.ts` (beside `extractCategory`) and the Engine's `extract_language` in `handlers/video.py` as the code to reuse.\n- **Conflicts R4:** the mismatch is now about C1's filtering (I2) changing the Engine, because the capture half is already done.\n- **Approach I1:** marked delivered, pointing to C1. I removed the \"land before a crawl to avoid a re-crawl\" advice, since it no longer applies.\n- **Rollback notes:** the backfill writes only `videos.language`.\n- I left the backfill (Out of scope, I3) and R1 (sparse data) unchanged; both still hold.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/18-english-subtitles.md": "<changes>\nCorrected the three statements in the subtitles plan that said the `videos` table has no language column.\n\n- **What the current code does \u2192 Language data:** this bullet used to say the table \"stores no language\". It now says the table stores `duration` and `language` (the PeerTube language code). The crawler fills `language` for the videos it crawls. `/api/video` fills it in `whitelist.db` when a video page is viewed, and the next sync overwrites that from `crawl.db`. Rows crawled before the column existed stay empty until a full re-crawl or a backfill, so coverage is sparse. I checked this against `engine/crawler/schema.sql:43` (the column), `videos-worker.ts:700` (`extractLanguage`) and `handlers/video.py:298/361` (the merge and the UPDATE). Line `schema.sql:29` is still the `CREATE TABLE videos` line.\n- **Scope \u2192 Out of scope:** \"adding a `language` column to the crawl\" is already delivered, so I replaced it with \"backfilling `videos.language` for rows crawled before the column existed\". That is the crawl-side language work still left, and it keeps the plan's intent of not doing corpus-wide language work. **Decision for you:** this is a new out-of-scope item rather than a plain deletion, so check that it matches what you want.\n- **Alternatives considered \u2192 Batch generation:** \"no language column to select by\" now reads \"`videos.language` empty for most existing rows\".\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/10-video-metadata-completeness.md": "<changes>\nClosed issue 10 as delivered: the status is now `enhancement, complete`, a Delivered comment lists the accepted limits, and the file is written to `docs/project/issues/archive/`. The original at `docs/project/issues/10-video-metadata-completeness.md` is still there because I have no tool that can delete a file. Please `git rm` it.\n\n- The `Status:` line reads `enhancement, complete`. The Problem, Proposed solution and Validation sections are unchanged.\n- There is a new `### Delivered` comment under `## Comments`, in the same style as archived issue 34. It covers:\n  - **What was delivered:**\n    - `/api/video` only writes to the database when the source instance returns a JSON object. When the instance fails, no UPDATE runs at all.\n    - `videos.language` exists in both producers.\n    - Category and language labels come from `engine/server/data/peertube_labels.py`, and the database keeps the raw ids and codes.\n    - The `video-taxonomy` block is on the video page.\n    - The checkpoint tests in `tests/tmp`.\n  - **Where the details live:** it points to the plan, to `engine/server/README.md` for how the route behaves, and to `DATA_BUILD.md` for the upgrade order, without repeating them.\n  - **Accepted limits:**\n    - Labels come from PeerTube's defaults only.\n    - An unset category shows as \"Unknown\".\n    - Removing a language or description at the source does not carry over.\n    - Saving is best-effort under the 5 s statement deadline.\n    - Stored refreshes are replaced at the next sync.\n    - The instance-direct fallback on the video page does not show category, language or tags, which differs from R6.\n  - **Still owed on main:** the crawler dist and the frontend dist both need rebuilding, and the video page still needs its manual check.\n- I checked these points against the code:\n  - The success guard (`dynamic is not None`) is in `video.py`.\n  - A null language id or an empty description keeps the value already in the database (`pick_text`).\n  - An unset category is stored as \"Unknown\" because the label is picked before the id.\n  - `/api/video` runs inside the `do_GET` `_statement_deadline()`, whose default is `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0`. A write that runs past it raises `OperationalError`, which is caught and logged.\n  - `fetchVideoMetadataFromInstance` does not map category, language or tags.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/10-video-metadata-completeness.md - the original of the moved file is still there because I have no tool that can delete a file; remove it with `git rm` so the only copy is the one in `docs/project/issues/archive/`.\n</not_on_checklist>",
    "step_10": "<moved>\nNone. The harvest stopped at Step 4 because the operator dismissed the approval question without answering. Nothing was moved. All four scope files are still in tests/tmp: test_10_video_metadata_completeness_phase1.py, _phase2.py, _phase3.py and _phase4.py. The plan that was put to the operator (all 15 test functions DURABLE) is in docs/project/plans/harvest-10-video-metadata-completeness-plan.md: phase1 migration test \u2192 new tests/active/test_whitelist_migrations.py; phase1's two crawl tests \u2192 tests/active/test_videos_worker.py; phase2+phase3 handler tests \u2192 new tests/active/test_video.py; phase4's three taxonomy tests \u2192 new tests/active/test_frontend_video_page.py.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nnone. test_groups in .un/skills/devsecops/config.json was not edited because the plan was not approved. The proposed changes, not applied, were: add test_whitelist_migrations.py, test_video.py and test_frontend_video_page.py, and add engine/crawler/src/db.ts and dist/db.js to test_videos_worker.py.\n</group_map>\n\n<mutations>\nnone. No mutation ran and no production file was touched, because no test moved. validate_tests.py was run only with --show-config.\n</mutations>\n\n<cleared>\nNothing. delete_me/ was not created and holds nothing. tests/tmp still holds the 4 in-scope files and the out-of-scope probe_*.py files. The record snapshot was byte-identical to tests/last_test_validation.json (checked with cmp), so it was moved back and the record is unchanged. Final counts: 0 moved, 0 retired, 0 mutations, 0 cleared. The harvest needs to be re-run from Step 1 once the operator approves.\n</cleared>"
  },
  "requirements": "### Purpose\n\nThe video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) must show what the source PeerTube instance currently says about a video, including its tags, category and language. Every `/api/video` request (`engine/server/api/handlers/video.py`, `handle_video_request`) must bring the server DB copy of the video's mutable fields up to date, and that copy also feeds search FTS (`videos_fts` triggers) and embeddings (`build-video-embeddings.py` reads `tags_json`/`category`). A failed or unreachable instance must never change stored data.\n\n### Baseline suite state\n\nPre-build suite exited 0 (variant: false). Resolved paths: active tests `tests/active`, working tests `tests/tmp`, plans `docs/project/plans`, archive `tests/archive`, delete_me `delete_me`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser/.worktrees/10`.\n\n### Current state found in the tree (context for later steps)\n\n- `fetch_instance_video_dynamic` already fetches `/api/v1/videos/{id}` plus `/api/v1/video-channels/{slug}`, normalises title/description/views/likes/dislikes/tags_json/category/nsfw, and the handler already UPDATEs `videos` (title, description, channel_name, views, likes, dislikes, popularity, tags_json, category, nsfw, last_checked_at), `channels`, and resets `instances.last_error/last_error_at/last_error_source`.\n- Defect: `fetch_instance_video_dynamic` always returns a non-empty dict (keys with `None` values) even when `fetch_instance_json` returned `None`. So `if dynamic and ...` is always true, and on instance failure the handler still writes `videos` (with DB fallback values), bumps `last_checked_at`, writes `channels`, and clears `instances.last_error`.\n- Defect: `to_tags_json` returns `None` for an empty list, so a source that removed all tags never propagates. `extract_category` drops a category that has only an `id`.\n- The `/api/video` response does not include tags, category, nsfw, language, duration or thumbnail.\n- There is no `language` column in any schema (crawler `engine/crawler/schema.sql`, whitelist `engine/server/db/jobs/whitelist_migrations.py`, `engine/server/db/jobs/sync-whitelist.py`). `duration`, `thumbnail_url`, `nsfw`, `tags_json` and `category` exist in both.\n- The crawler (`engine/crawler/src/videos-worker.ts` `extractCategory`) stores the category label, or `String(id)` when no label exists, so DB rows can hold numeric category strings such as \"15\".\n- No active test covers `/api/video` today.\n\n### R1 \u2014 Successful-refresh rule (a fix to current behaviour)\n\n- A refresh is successful exactly when the video detail fetch `/api/v1/videos/{id}` returns a JSON object (dict).\n- The existing fetch contract stays as it is: `urlopen(..., timeout=8)`, catching `HTTPError`, `URLError`, `TimeoutError`, and a non-200 status returning `None`. In addition, a body that is not valid JSON, or valid JSON that is not an object, is treated as failure (returns no data) instead of raising out of the handler.\n- A failure of the secondary channel-detail fetch (`/api/v1/video-channels/{slug}`) does not make the refresh unsuccessful. The channel fields then fall back as they do today.\n- On success: one transaction UPDATEs the `videos` row (fields per R2, plus `popularity` and `last_checked_at = now`), UPDATEs the `channels` row as today, and resets `instances.last_error`, `last_error_at` and `last_error_source` for the host. The existing `sqlite3.OperationalError` catch-and-log is kept.\n- On failure: no UPDATE to `videos`, `channels` or `instances` runs at all. `last_checked_at` is unchanged, `instances.last_error` is unchanged, and the response is built field by field from the DB row.\n\n### R2 \u2014 Field mapping rules (one write path)\n\nThere is a single UPDATE path in the handler. For each mutable field, a value present and valid in the source payload overwrites the DB value. A value that is absent, null or invalid keeps the DB value, both in the response and in what is written.\n\n- `title`: source `name` (or `title`), a non-empty trimmed string; otherwise keep DB.\n- `description`: source `description`, a non-empty trimmed string; otherwise keep DB. An empty string keeps DB (current `pick_text` behaviour, deliberately kept).\n- `views`, `likes`, `dislikes`: int-like source values (existing aliases `viewsCount`/`views_count`, etc.); otherwise keep DB.\n- `tags_json`: if source `tags` is a list, overwrite with the JSON array of its string elements. An empty list is stored as `\"[]\"` so removals propagate. If `tags` is absent or not a list, keep DB.\n- `category`: source `category` object \u2192 its `label` (or `name`) if non-empty, else its `id` as a string. A plain string or number is stored as a string. Absent/null keeps DB.\n- `language` (new column): source `language` object \u2192 its `id` (the PeerTube language code, e.g. `\"en\"`). A plain string is stored as is. Absent/null or a null id keeps DB.\n- `nsfw`: source boolean/int-like \u2192 0/1 (existing `to_nullable_bool`); absent/null keeps DB.\n- `duration`: source `duration`, int-like seconds; otherwise keep DB.\n- `thumbnail_url`: source `thumbnailUrl`, else `thumbnailPath`, resolved to an absolute `https://{host}...` URL (existing `resolve_asset_url`); otherwise keep DB.\n- `popularity`: recomputed from the merged views/likes as today, written only on success.\n- `last_checked_at`: set to now only on success.\n\nA partial source response (for example, stats present but tags/category missing) must never wipe the stored tags or category.\n\n### R3 \u2014 Language column (schema change across producers)\n\n- Add `language TEXT` (nullable) to the `videos` table in `engine/crawler/schema.sql`. The crawler DB layer (`engine/crawler/src/db.ts`, including its videos insert/upsert and the `videos_new` rebuild) and `engine/crawler/src/videos-worker.ts` must extract and persist `language` from the PeerTube video payload using the same rule as R2 (the language id/code).\n- Add `language` to the server whitelist `videos` schema through a new migration in `engine/server/db/jobs/whitelist_migrations.py` that is safe on existing databases (additive column). `engine/server/db/jobs/sync-whitelist.py` must create and copy the column.\n- `fetch_video_row` selects `v.language`.\n- Rebuild the committed crawler `dist/` JS if the repository keeps it in sync with `src/` (`engine/crawler/dist/db.js`, `videos-worker.js`).\n\n### R4 \u2014 Category and language display labels\n\n- A static, stdlib-only map in the server holds PeerTube's default video categories (ids 1\u201318 \u2192 labels, e.g. 1 Music, 2 Films, 3 Vehicles, 4 Art, 5 Sports, 6 Travels, 7 Gaming, 8 People, 9 Comedy, 10 Entertainment, 11 News & Politics, 12 How To, 13 Education, 14 Activism, 15 Science & Technology, 16 Animals, 17 Kids, 18 Food) and PeerTube's default language codes \u2192 labels.\n- When `/api/video` builds its response, a stored category that is a digit-only string resolves through the map to its label. Any other stored value is shown as is. An unknown id is shown as the raw value. A stored language code resolves to its label; an unknown code is shown as the raw code.\n- Named simplification: this map covers only PeerTube's defaults. Instances with plugin-added or renamed categories/languages display the raw id or code. Upgrade path: fetch and cache the instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`.\n\n### R5 \u2014 `/api/video` response contract\n\nAll existing response keys are kept unchanged. New keys, each from the merged value (source on success, else DB):\n\n- `tags`: a list of strings parsed from `tags_json` (empty list when null, empty, or unparseable).\n- `category`: the display label per R4, or `\"\"`.\n- `language`: the display label per R4, or `\"\"`.\n- `nsfw`: boolean or `null`.\n- `duration`: integer seconds or `null`.\n- `thumbnailUrl`: string or `\"\"`.\n\nThe Client backend proxy (`client/backend/server.py`, `/api/video` in `PROXY_READ_GET_ROUTES`) passes the body through, and must continue to do so with the new keys.\n\n### R6 \u2014 Video page UI\n\n- In the existing metadata area of `client/frontend/video-page.html` (near `video-meta-row` / `video-description`), add a compact metadata block that shows:\n  - the category label (hidden when empty),\n  - the language label (hidden when empty),\n  - tags as chips, with the empty state \"No tags\" when the list is empty.\n- `client/frontend/src/pages/video-page/index.ts`: extend `VideoMetadata` with `tags`, `category` and `language`. Fill them in `fetchVideoMetadataFromServer` from the new response keys, and in the instance-direct fallback `fetchVideoMetadataFromInstance` from the PeerTube payload (`tags` list, `category.label`, `language.label`). Render them in `loadVideo`. All values are HTML-escaped (existing `escapeHtml`) or set via `textContent`.\n- Styling goes in `client/frontend/src/video.css`, compact and consistent with the existing metadata styles. Rebuild `client/frontend/dist` if the repository keeps it committed.\n\n### R7 \u2014 Tests (active suite, `tests/active`)\n\nA new test module for the `/api/video` handler. It uses a SQLite DB created from the production server (whitelist) `videos`/`channels`/`instances` schema, not a hand-picked column subset, and stubs the instance fetch (`fetch_instance_json`) with no network access. It covers:\n\n- Success fixture: after one request, the DB row holds the source `title`, `description`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, `language`, `duration`, `thumbnail_url`, and a `last_checked_at` newer than before. `instances.last_error`, `last_error_at` and `last_error_source` are reset to NULL. The response carries the new keys per R5.\n- Instance-fail fixtures: at least one each for a caught network error (e.g. `URLError`/`TimeoutError`, via the stub returning `None`) and a malformed/non-object body. Assert every `videos` column is unchanged (no overwrite, `last_checked_at` unchanged), the `channels` row is unchanged, `instances.last_error` is still set, and the response values equal the DB values.\n- Partial-response regression: a source payload with stats but no `tags` and no `category` keeps the stored `tags_json` and `category`. A payload with `tags: []` stores `\"[]\"` and returns `tags: []`.\n- Integration: a source metadata change (e.g. new title and tags) between two requests is reflected in the second `/api/video` response and in the DB.\n- Label mapping: a stored digit-only category (e.g. `\"15\"`) is returned as its label (\"Science & Technology\"); an unknown id is returned raw; a language code is returned as its label.\n- Crawler: `language` is persisted by the crawler videos path (extend `tests/active/test_videos_worker.py`, which already builds from `engine/crawler/schema.sql`).\n- Whitelist migration: the new migration adds `language` to an existing DB without losing rows.\n\nManual validation (not automated): tags, category and language render on the video page, and the \"No tags\" empty state shows for a video without tags.\n\n### Out of scope\n\n- Fetching per-instance category/language lists (R4 upgrade path).\n- Changing the refresh cadence or adding caching of `/api/video`.\n- Displaying nsfw, duration or thumbnail on the video page (they are refreshed, stored and returned, but R6 renders only category, language and tags).",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe work falls into four parts, each confined to the files the requirements name: the handler, the schema, the page and the tests. What follows was checked against `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, the crawler's `schema.sql`, `db.ts` and `videos-worker.ts`, the video page sources and `tests/active`.\n\n**1. Handler: one success signal, one merge, one write (R1, R2, R5)** in `engine/server/api/handlers/video.py`.\n\n- **`fetch_instance_json`** keeps its contract: `urlopen(..., timeout=8)`, the same three caught exceptions, and a non-200 status still returns `None`. Two cases are added, both logged at info like the network failures:\n  - a body that fails to decode or parse (`ValueError`, which covers both `JSONDecodeError` and `UnicodeDecodeError`) returns `None`;\n  - a parsed value that is not a `dict` returns `None`.\n- **`fetch_instance_video_dynamic`** returns `None` when the detail fetch gives no dict. That is the single success signal R1 defines. The channel-detail fetch keeps its current fallback, so its failure never turns a refresh into a failure.\n  - Presence is kept distinct from emptiness. `tags` is no longer coerced with `or []`, so a missing key and an empty list stay different.\n  - `to_tags_json` returns `\"[]\"` for an empty list and `None` only when the value is not a list.\n  - `extract_category` falls back to `str(id)` when the object has no label, and turns a number into a string.\n  - A small `extract_language` returns the object's `id` (or a plain non-empty string). A null id returns `None`.\n  - `duration` goes through `pick_number`. `thumbnail_url` goes through `resolve_asset_url(host, thumbnailUrl or thumbnailPath)`.\n  - A `None` in the dynamic dict always means \"keep the DB value\".\n- **`fetch_video_row`** also selects `v.language`, `v.duration` and `v.thumbnail_url`. The last two are needed so the fallback response can serve them from the DB.\n- **`handle_video_request`** builds one merged set of values:\n  - each field is the source value when it is present and valid, otherwise the DB value, using the existing `pick_text`/`pick_number`/None-check rules;\n  - that one set feeds both the response and the UPDATE, so the two can never disagree;\n  - when `dynamic is None` (fetch failed, or no host), the merged values are just the DB row and the whole write block is skipped. No `videos`, `channels` or `instances` statement runs;\n  - on success the existing single transaction runs with the SET list extended by `language`, `duration` and `thumbnail_url`, plus `popularity` and `last_checked_at`. The `channels` update and the `instances.last_error*` reset stay as they are, and so does the `OperationalError` catch.\n- **Response.** Every existing key is kept, plus:\n  - `tags`: parsed from the merged `tags_json`, keeping string elements only, and `[]` on null, empty or unparseable;\n  - `category` and `language`: display labels (see part 2), or `\"\"`;\n  - `nsfw`: a bool or `null`;\n  - `duration`: an int or `null`;\n  - `thumbnailUrl`: a string or `\"\"`.\n- **Client proxy.** `client/backend/server.py` needs no change: `/api/video` is in `PROXY_READ_GET_ROUTES`, which passes the body through.\n\n**2. Display labels (R4).** A new stdlib-only module, `engine/server/data/peertube_labels.py`, holds two dicts:\n\n- PeerTube's default categories: `\"1\"`\u2013`\"18\"` mapped to labels, exactly as listed in R4.\n- PeerTube's default language codes mapped to labels, copied once from a stock instance's `/api/v1/videos/languages` output and committed as a literal dict.\n\nIt has two tiny lookup functions:\n- category: a digit-only string resolves through the map; any other value, or an unknown id, is returned as it is;\n- language: a known code resolves to its label; an unknown code is returned raw.\n\nThe handler uses them only when it builds the response. Stored values are never rewritten to labels, so FTS and embeddings keep what the crawler writes today.\n\n**3. `language` column across the producers (R3).**\n\n- **Crawler (`engine/crawler`):**\n  - `schema.sql` gets `language TEXT` after `category`.\n  - `db.ts`:\n    - an additive step in `applyBaseSchema` runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. This is required: `CREATE TABLE IF NOT EXISTS` never adds columns, and without it every existing `crawl.db` fails `sync-whitelist.py`'s superset check against `schema.sql`;\n    - the `videos_new` rebuild in `migrateVideos` carries `language`, with the same conditional-expression pattern (`hasLanguage ? \"language\" : \"NULL\"`) it uses for the error columns;\n    - `VideoUpsertRow` gains `language`, and the upsert gains the column in its INSERT list, in `ON CONFLICT ... language = excluded.language`, and in the positional `run(...)` arguments.\n  - `videos-worker.ts`: `PeerTubeVideo` gains a `language` field, a new `extractLanguage` follows R2's rule (object \u2192 `id`; non-empty string \u2192 itself; otherwise `null`), and `toVideoRow` sets it.\n  - `dist/db.js` and `dist/videos-worker.js` are rebuilt with `npm run build` and committed. `test_videos_worker.py` asserts the dist is not stale.\n- **Server whitelist DB:**\n  - `sync-whitelist.py`: `ensure_content_schema`'s `CREATE TABLE videos` gets `language TEXT`. Copying needs nothing more, because `VIDEO_COLUMNS` is parsed from `schema.sql`, so both `rebuild_content_tables` and `ensure_schema_compatibility` pick the column up automatically.\n  - `whitelist_migrations.py`: a new `migrate_videos_language(conn)` checks `_columns` and, if the column is missing, runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is idempotent, keeps every row, and leaves the FTS triggers alone because they do not reference `language`. `migrate_whitelist_schema` calls it after `migrate_videos_schema`, so even a DB that needed the old rebuild ends up with the column.\n  - The Python `videos_new` rebuild also carries `language` conditionally. That way no rebuild path can drop it.\n- **Updater worker:** `updater-worker.py` merges through `shared_columns`, which works by column name, so it needs no change.\n\n**4. Video page (R6).**\n\n- `video-page.html`: a compact `video-taxonomy` block goes between `video-meta-row` and `video-description`. It holds a category span, a language span and a tags container.\n- `index.ts`:\n  - `VideoMetadata` gains `tags: string[]`, `category: string` and `language: string`;\n  - `fetchVideoMetadataFromServer` fills them from the new keys, keeping only string elements of `tags`;\n  - `fetchVideoMetadataFromInstance` fills them from the PeerTube payload (`tags` list, `category.label`, `language.label`);\n  - `loadVideo` renders them with `textContent` and `createElement` for the chips, so no HTML is interpolated. Category and language are hidden when empty, and the tag list shows \"No tags\" when it is empty.\n- `video.css` gets compact chip and label styles that reuse the existing metadata sizes and colours.\n- `client/frontend/dist` is committed, so it is rebuilt.\n\n**5. Tests (R7).**\n\n- **New `tests/active/test_video_handler.py`.**\n  - It loads `sync-whitelist.py` with `spec_from_file_location` (the precedent in `test_repair_video_channel_names.py`) and builds a `tmp_path` DB with its `ensure_whitelist_schema` + `ensure_content_schema`. That is the production schema, triggers included.\n  - It imports `handlers.video` with `engine/server` and `engine/server/api` on `sys.path`.\n  - The server is a `SimpleNamespace` with `db` (row factory `sqlite3.Row`), `db_lock`, `video_error_threshold` and `popularity_like_weight`. `respond_json` is monkeypatched to capture the status and body.\n  - **Fetch stubs, no network:**\n    - `fetch_instance_json` is replaced with a path-keyed fake for the success, partial-payload, integration and label cases, and returns `None` for the network-error case;\n    - for the malformed-body cases, `video.urlopen` is replaced with a fake response carrying a non-JSON body and a JSON list, and with one that raises `URLError`. This exercises the real parse guard.\n  - **Cases:** success, network failure, malformed body, a partial payload keeping tags and category, `tags: []` \u2192 `\"[]\"` / `[]`, two sequential requests with changed source data, and the label mapping (`\"15\"` \u2192 \"Science & Technology\", unknown id raw, language code \u2192 label).\n  - **Failure assertions:** a snapshot of the whole `videos` row and the whole `channels` row, taken with `SELECT *` before and after, so every column is compared, not a chosen subset.\n- **Migration test.** It builds a legacy `videos` table inline with the pre-change columns (the old shape can only be written out, since the current helpers will create the new one), inserts rows, runs `migrate_whitelist_schema`, and asserts the column exists, the rows are intact, and a second run is a no-op.\n- **`test_videos_worker.py`.** The stand-in payload gains `language: {id: \"en\", label: \"English\"}` and the test asserts the stored `language`. A second case pre-creates a `crawl.db` without the column, to prove the additive crawler migration.\n\n### Alternatives considered\n\n- **Success signal.** One option is a sentinel or exception from `fetch_instance_video_dynamic`, another is having it return `(ok, data)`. Returning `None` on detail failure is the smallest change and matches how `fetch_instance_json` already reports failure. Checking for \"any non-None field\" was rejected: a valid source that lacks every optional field would then count as a failure.\n- **Two write paths (stats-only vs full).** Rejected, because R2 requires a single UPDATE path. With a single merge, \"keep DB when absent\" is just \"write back the DB value\", which leaves the row unchanged.\n- **Storing labels instead of ids for language.** Rejected, because R2 fixes the stored value as the code. Resolving at response time keeps the map an honest display concern and lets the upgrade path (per-instance lists) plug in without a data migration.\n- **Label map placement.**\n  - Inline in `video.py`: rejected, because a ~200-entry language table would bury the handler.\n  - A JSON data file: rejected, because it adds a load step and a file path for no gain over a Python literal.\n  - One small module is the minimum.\n- **Migrating the whitelist DB at Engine startup.** Rejected. The conftest `engine` fixture starts the Engine against the repo's live `engine/server/db/whitelist.db`, so a startup `ALTER TABLE` would change a shared DB from a worktree test run. The migration stays in `migrate-whitelist.py`, the existing operator path. The same applies to the crawler's migration, which only runs when the crawler opens its own DB.\n- **Adding `language` to `videos_fts`.** Not required, and it would force an FTS rebuild. Left out.\n- **Malformed-body test through `fetch_instance_json` stubs only.** Rejected. A stub that returns a list would test only the handler, not the new parse guard, so those cases stub `urlopen` one level lower.\n\n### Gotchas and risks\n\n- **Deployment order.** After the merge, `fetch_video_row` selects `v.language`. An Engine started on an unmigrated `whitelist.db` answers every `/api/video` with a 500. `sync-whitelist.py` likewise refuses an unmigrated whitelist DB (the exact column check, with the existing \"run migrate-whitelist.py\" message) and an un-upgraded `crawl.db` (the superset check). The runbook order is:\n  1. merge;\n  2. run the crawler once, or open `crawl.db` with it, so the additive migration runs;\n  3. run `migrate-whitelist.py` on every `whitelist.db`, the prod one included;\n  4. restart the Engine.\n  \n  This goes in `DATA_BUILD.md` / the harvest notes.\n- **Unset category shows \"Unknown\".** When no category is set, PeerTube returns `{id: null, label: \"Unknown\"}`. R2 takes the label whenever it is non-empty, so such videos store and show \"Unknown\". The crawler already stores it today, so the data does not change, but the page will now show \"Unknown\" as a category and the instance-direct fallback will do the same through `category.label`. Language behaves differently: a null id keeps the DB value, so an unset language stays hidden.\n- **A removed language never propagates.** PeerTube reports \"unset\" as a null id, which R2 treats as \"keep DB\". The same holds for a description cleared to `\"\"` (deliberately kept `pick_text` behaviour) and for title.\n- **Uncaught fetch errors.** Exceptions outside the kept contract, such as `ConnectionResetError` or `http.client.IncompleteRead`, still propagate as a 500. They are raised before any write, so the rule that stored data never changes on failure still holds. Widening the catch is a one-line follow-up if wanted.\n- **The FTS trigger now fires only on real refreshes.** That is a behaviour improvement, but each successful `/api/video` still rewrites the row's FTS entry, as it does today.\n- **Embeddings go stale.** They are not recomputed when tags or category change through `/api/video`. `build-video-embeddings.py` picks the new values up on its next run, as it does today.\n- **Column order differs.** A fresh DB has `language` next to `category`, while a migrated DB has it last. Every reader I found uses names (`shared_columns`, named INSERT/SELECT lists, `sqlite3.Row`).\n- **The language map is transcribed by hand.** A wrong or missing entry shows the raw code. That is harmless, but it is a fidelity risk.\n- **Dist rebuilds.** Crawler dist needs `engine/crawler/node_modules` (`npm install && npm run build`), because `test_videos_worker.py` fails on a stale dist. The client dist rebuild changes hashed asset names in `dist/video-page.html`.\n\n### Tradeoffs the operator accepts\n\n- **Default-only labels (named simplification, R4).** Categories and languages that an instance adds or renames show as raw ids or codes. The ceiling is PeerTube's stock lists. The upgrade path is fetching and caching `/api/v1/videos/categories` and `/api/v1/videos/languages` per instance.\n- **Manual migration step.** A deploy needs `migrate-whitelist.py` run before the Engine restarts. The build does not migrate automatically, to keep worktree tests off the shared DB.\n- **\"Unknown\" category and asymmetric removal.** A video with no category shows \"Unknown\", and a language removed at the source is not cleared. Both follow R2 literally. Changing either means treating a `null` id as \"cleared\", which is a requirements change.\n- **Failed refresh leaves the error visible.** On failure the page shows DB values with no staleness indicator, and `instances.last_error` stays as the last writer left it. This build does not set a new error.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_json() (lines 75-87)\">\n**What changes:** it keeps `urlopen(req, timeout=8)`, the `(HTTPError, URLError, TimeoutError)` catch and the non-200 \u2192 `None` return. Two new failure paths return `None` and log at info: a `ValueError` from `.decode(\"utf-8\")` or `json.loads` (this covers both `UnicodeDecodeError` and `JSONDecodeError`), and a parsed value that is not a `dict`.\n\n**What depends on it:** `fetch_instance_video_dynamic` calls it twice, once for the detail and once for the channel. The channel call at line 176 already checks `isinstance(channel_detail, dict)`, so returning `None` for a non-dict does not change it. The new test replaces `video.urlopen` to reach this function directly. `urlopen` is imported by name at line 14, so the monkeypatch must target `handlers.video.urlopen`, not `urllib.request.urlopen`.\n\n**Regression risk: low.** Today a malformed body raises `ValueError` out of `do_GET`. `similar.py:438-441` re-raises anything that is not \"interrupted\", so the socket closes with no response and the Client proxy sees a transport error, retries once, then answers 502. After this change the same case becomes a DB-fallback 200. Exceptions outside the contract still drop the connection the same way: `ConnectionResetError`, `http.client.IncompleteRead`, `RemoteDisconnected`, and `ssl.SSLError` if it is not wrapped in `URLError`. The plan's \"500\" wording is inaccurate: there is no 500 handler, the connection just closes. The `# pragma: no cover` on the except line should come off once tests cover it.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_video_dynamic() (lines 162-205)\">\n**What changes:** it returns `None` when the detail fetch does not give a dict; this is the single success signal. `tags` is no longer coerced with `or []`. New keys: `language` (from `extract_language`), `duration` (from `pick_number(detail.get(\"duration\"))`) and `thumbnail_url`.\n\n**Things to get right:**\n- `resolve_asset_url` returns `\"\"`, not `None`, when the value is missing (line 92-93). `thumbnail_url` therefore has to map `\"\"` to `None`, or a payload with no thumbnail overwrites the DB value with `\"\"`. This breaks R2's rule that `None` means \"keep the DB value\".\n- `pick_number` accepts `bool`, because `bool` is a subclass of `int`, so `True` becomes 1. That is harmless for `duration`.\n- `account_avatar_url` is already `\"\"`-defaulted and is only used in the response, which is unchanged.\n- `channel.get(...)` needs `detail.get(\"channel\")` to be a dict. Today it runs `detail.get(\"channel\") or {}`, and a non-dict truthy `channel` (a string, say) would raise `AttributeError`. This is a pre-existing gap and now worth guarding with `isinstance`, because the function runs only on success.\n- Tag strings are not trimmed or deduplicated.\n\n**What depends on it:** only `handle_video_request` (line 227). The grep found no other importer of `handlers.video` apart from `similar.py:84`.\n\n**Regression risk: medium.** This function is the core of R1 and R2. Returning `{}` instead of `None` on failure would reintroduce the \"always truthy\" defect, but only if the caller keeps the `if dynamic` test. The caller must test `dynamic is None`, not truthiness, or a success whose dict happens to be empty would be treated as a failure.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"to_tags_json() (lines 132-137)\">\n**What changes:** a list returns `json.dumps([string elements])`, and an empty list (or a list of only non-strings) returns `\"[]\"`. Anything that is not a list returns `None`.\n\n**What depends on it:** only `fetch_instance_video_dynamic`.\n\n**Downstream effects of `\"[]\"` now being stored in whitelist.db:**\n- The FTS trigger indexes `\"[]\"`, which tokenises to nothing, so it is harmless.\n- `build-video-embeddings.parse_tags(\"[]\")` returns `[]` (line 19-26).\n- The crawler's `listVideosForTags` treats `'[]'` as missing, but it reads crawl.db, not whitelist.db, so it is unaffected.\n\n**Regression risk: low.** `json.dumps` defaults to `ensure_ascii=True`, which is the same as today, so non-ASCII tags are stored `\\u`-escaped. FTS then indexes the escape sequences rather than the words. This is existing behaviour, but it now also applies to refreshed tags, and the crawler (TS `JSON.stringify`) stores raw UTF-8. The build could pass `ensure_ascii=False` to match the crawler. That is a judgment call, so it is flagged here rather than required.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"extract_category() (lines 140-146)\">\n**What changes:** for an object: `label` or `name`, else `str(id)` when the id is not `None`. A number becomes `str(n)`.\n\n**Gap in the current code:** a plain string is returned as-is, including `\"\"` and whitespace. A non-`None` `\"\"` then overwrites the stored category, which R2 forbids (\"absent/null keeps DB\"). Plain strings should go through `pick_text`. Numbers need a `bool` guard (`isinstance(True, int)` is true).\n\n**PeerTube behaviour:** an unset category is `{id: null, label: \"Unknown\"}`, which gives \"Unknown\". That matches the crawler's `extractCategory` (videos-worker.ts:838-848), so the stored value agrees with what the crawler writes.\n\n**Regression risk: low.** Only the dynamic dict uses it.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"new extract_language() helper\">\n**What changes:** a new helper. For an object it returns `id` as a non-empty string; for a plain non-empty string it returns that string; otherwise `None`. A null id (PeerTube's unset `{id: null, label: \"Unknown\"}`) returns `None`, which keeps the DB value.\n\n**What depends on it:** `fetch_instance_video_dynamic`. It should mirror the crawler's new `extractLanguage` so both producers store the same code.\n\n**Regression risk: low.** Watch for `id` given as a non-string. PeerTube language ids are strings such as `\"en\"` or `\"zh-Hans\"`, so use `pick_text` rather than `str()`, so that `0` or `False` never become codes.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_video_row() SELECT (lines 33-69)\">\n**What changes:** it also selects `v.language`, `v.duration` and `v.thumbnail_url`. `duration` and `thumbnail_url` already exist in both schemas (schema.sql:45-46, sync-whitelist.py:366-367), so only `language` needs the migration.\n\n**What depends on it:** `handle_video_request` only. The row goes into `dict(row)`, so it is read by column name, and column order does not matter.\n\n**Regression risk: high (deployment).** On any whitelist.db that has not been migrated, this SELECT raises `sqlite3.OperationalError: no such column: v.language`. It is not \"interrupted\", so `similar.py:438-441` re-raises it and the Engine drops the connection on every `/api/video`. What the browser sees:\n- The Client proxy retries once, then answers 502 `ENGINE_PROXY_UNAVAILABLE`.\n- `fetchVideoMetadataFromServer` returns null, and the page falls back silently to the instance-direct fetch. The failure is visible only in the logs.\n- `tests/run-arch-split-smoke.sh:582` and `run-installers-smoke.sh:647` assert 200 and will fail.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request(): merge block (lines 226-258) and write block (lines 292-358)\">\n**What changes:** one merged value set feeds both the response and the UPDATE.\n- `dynamic is None` (fetch failed, or `instance_domain` is empty, which today gives `{}` at line 227) skips the whole write block.\n- On success the UPDATE SET list gains `language`, `duration` and `thumbnail_url`.\n\n**Things to keep:**\n- The merge currently uses `dynamic.get(\"title\") or row.get(\"title\")`, which is falsy-based. For title and description that is fine, because `pick_text` never returns `\"\"`. For numeric and nullable fields keep the existing `is None` pattern.\n- `channel_display` falls back to `row[\"channel_name\"]`, and the UPDATE writes it into `videos.channel_name`. Keep that.\n- `channels` UPDATE: when `channel_slug` is `None` (no channel in the payload and no `channel_slug` from the join), it writes `channel_name = NULL`. Today it runs on failure too; on success only it still can. This is pre-existing and should be flagged, not changed.\n- The `instances` reset runs even when no `instances` row exists for the host; it is a no-op.\n- `popularity`: `compute_popularity(views, likes, row[\"published_at\"], ...)`. Keep it.\n\n**Transaction:** `with server.db_lock: with server.db:` commits or rolls back as one unit, so the `OperationalError` catch leaves nothing half-written.\n\n**What depends on it:** `similar.py:495-497`. The `videos_fts_au` trigger fires on every successful UPDATE, including no-op field sets. `last_checked_at` is always bumped on success, so every successful request rewrites the row's FTS entry. That is today's behaviour, now limited to successes.\n\n**Regression risk: high.** This is the heart of R1 and R2. Today a failure still writes: it bumps `last_checked_at`, clears `instances.last_error`, and can set `channels.channel_name` to NULL. After the change, failures stop all of that, and any operational process that relied on those side effects loses them. None was found by grep.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"response dict (lines 271-290)\">\n**What changes:** all 18 existing keys are kept. New keys:\n- `tags`: parse the merged `tags_json`, keep string elements only, and give `[]` on NULL, `\"\"`, invalid JSON or a non-list.\n- `category`: label via `peertube_labels`, or `\"\"`.\n- `language`: label, or `\"\"`.\n- `nsfw`: `bool(int)`, or `None`. Stored 0/1 becomes `False`/`True`.\n- `duration`: int, or `None`. The stored INTEGER passes through.\n- `thumbnailUrl`: string, or `\"\"`.\n\n**What depends on it:**\n- The Client proxy passes the body through as bytes (`client/backend/server.py:606-619`).\n- `index.ts fetchVideoMetadataFromServer` reads only the keys it knows, so the extra keys are harmless to the current build.\n\n**Regression risk: low.** `tags_json` from the crawler can hold a JSON string rather than a list, which `build-video-embeddings.parse_tags` tolerates by treating it as one tag. The response parser should return `[]` for a non-list, as R5 says. Note that this differs from `parse_tags` on the same input.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"helpers resolve_asset_url, pick_text, pick_number, to_nullable_bool (lines 90-159)\">\n**What changes:** nothing. Their contracts matter to the merge:\n- `resolve_asset_url` returns `\"\"` on a missing value and always uses `https://`, while the crawler's `resolveAssetUrl` keeps the crawl protocol and adds a `/` when there is none.\n- `pick_text` trims.\n- `pick_number` truncates floats and accepts `bool`.\n- `to_nullable_bool` maps an unknown type to `None`.\n\n**Regression risk:**\n- A refreshed `thumbnail_url` may differ in form from the crawler's (`thumbnailPath` against the crawler's `thumbnailUrl ?? thumbnailPath ?? thumbnail_path ?? thumbnail`). The plan picks `thumbnailUrl or thumbnailPath` only. A PeerTube payload with only `thumbnail_path` or a `thumbnail` object keeps the DB value. That is safe.\n- A relative path with no leading `/` gives `https://hostpath`, which is malformed. PeerTube always sends a leading `/`, so this is low risk.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"do_GET statement_deadline (lines 433-441), _dispatch_get /api/ rate limit (447-449), /api/video route (495-497)\">\n**What changes:** nothing in code, but this interaction was not in the plan.\n\n**Deadline:** `/api/video` runs inside `statement_deadline(statement_timeout_seconds)`, 5 s by default. The deadline is an absolute thread-local time set at request start (`data/db.py:44-64`). The two outbound fetches (up to 8 s + 8 s) run before the UPDATE, so for any instance slower than about 5 s in total:\n- the UPDATE, and the triggers it fires, raise `OperationalError('interrupted')`;\n- the handler's existing catch logs a warning and answers 200 with the fresh values, but nothing is persisted.\n\nA slow instance can therefore never be refreshed in the DB. This is today's behaviour as well, and the handler's `OperationalError` catch is what keeps it a 200. The new tests use a `SimpleNamespace` server with no deadline, so they will not show this.\n\n**Rate limit:** `/api/` routes, `/api/video` included, go through the Engine's 60/min per-IP limiter. The earlier assumption that it is not rate-limited is wrong. A 429 is answered before the handler runs.\n\n**What depends on it:** every `/api/video` request.\n\n**Regression risk: medium (latent).** The DB-write guarantee is best-effort for slow sources. Document it; widening the deadline is out of scope.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"statement_deadline / install_deadline_handler / connect_db (lines 31-81)\">\n**What changes:** nothing.\n\n**What depends on it:** `server.db` carries the progress handler. The new handler test builds its own `sqlite3.connect` without it, so it runs with no deadline.\n\n**Regression risk:** none from the build. The test cannot cover the deadline behaviour described in the `similar.py` entry.\n</impact>\n<impact path=\"engine/server/data/peertube_labels.py\" element=\"new module: category map, language map, two lookup functions\">\n**What changes:** a new stdlib-only module holding:\n- `CATEGORY_LABELS`: `\"1\"`\u2013`\"18\"`, exactly R4's list, including `\"11\": \"News & Politics\"`, `\"12\": \"How To\"` and `\"15\": \"Science & Technology\"`.\n- a language-code map copied from stock PeerTube.\n- a category lookup: digit-only strings go through the map, and anything else or an unknown id is returned unchanged.\n- a language lookup: known codes resolve, and unknown codes are returned raw.\n\nIt follows the `engine/server/data/*.py` style (a module docstring, `from __future__ import annotations` as in `whitelist_migrations`), with a docstring on every function.\n\n**What depends on it:** the video.py response builder only, which imports it as `from data.peertube_labels import ...`, matching the existing `from data.time import now_ms`.\n\n**Regression risk: low.**\n- The map is transcribed by hand, so there is a fidelity risk.\n- PeerTube language codes are case-sensitive (`zh-Hans`, `zh-Hant`, `pt-PT`), so the lookup must not lowercase.\n- Use `str.isdigit()` together with `isascii()`, or a Unicode digit such as `\"\u0661\u0665\"` counts as digit-only. Harmless, since the result is an unknown id returned raw.\n- The Engine imports `data.*` at startup, so the module must do no work at import beyond the literals.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"PROXY_READ_GET_ROUTES / PROXY_ALLOWED_QUERY_PARAMS['/api/video'] (lines 81-88) and _proxy_engine_request (570-680)\">\n**What changes:** nothing. The body is passed through as bytes, and `row_filter` is `None` for `/api/video`.\n\n**What depends on it:** the page. `ENGINE_PROXY_TIMEOUT_SECONDS = 10` with `ENGINE_PROXY_RETRY_COUNT = 1`. The Engine's `/api/video` can take up to 16 s on a slow source, which exceeds the proxy timeout. The proxy then retries, so a second Engine request (and possibly a second write) runs for the same page view. This is pre-existing; it is noted because each successful request now writes more columns.\n\n**Regression risk: none from the code.** An unmigrated DB turns into a 502 here, as described in the `fetch_video_row` entry.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"videos CREATE TABLE (lines 29-61)\">\n**What changes:** `language TEXT` is added after `category` (line 42).\n\n**What depends on it:**\n- `sync-whitelist.py` parses the column list at import (lines 92-96), so `VIDEO_COLUMNS` gains `language`. This drives the exact check against the whitelist DB, the superset check against crawl.db, and the copy column list.\n- `db.ts` runs `schemaSql` twice in `applyBaseSchema`.\n- `updater-worker.init_staging_db` creates staging from it (lines 548-565).\n- `tests/active/test_videos_worker.py` and `test_repair_video_channel_names.py` build crawl-shaped DBs from it.\n\n**Regression risk: medium.** `CREATE TABLE IF NOT EXISTS` never adds the column to an existing crawl.db. The first `db.exec(schemaSql)` in `applyBaseSchema` also runs every `CREATE INDEX` against the old table, so no index on `language` may be added to schema.sql, or the first exec fails on old DBs before the migration can run. The parser splits on top-level commas; a plain `language TEXT,` line parses cleanly.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"applyBaseSchema() (lines 65-71): new additive language step\">\n**What changes:** after `migrateVideos(db)` and before the second `db.exec(schemaSql)`, a step checks `getColumns(db, \"videos\")` and runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. It must run after `migrateVideos`, so that a rebuilt table is also covered, and it must be guarded with `tableExists`.\n\n**What depends on it:** every store constructor: `CrawlerStore` (line 520), `ChannelStore` (792) and `VideoStore` (1203). Any crawler CLI that opens crawl.db migrates it: instances, channels, videos, counts. `openExistingDb` (videos-worker.ts:940) opens the prod DB read-only with no migration, and only reads `video_id`, so it is safe.\n\n**Regression risk: medium.** It is the only way an existing crawl.db can pass `sync-whitelist`'s superset check. `ALTER ADD COLUMN` is a cheap metadata change, but it needs a write lock, and a concurrently running crawler process sharing crawl.db will contend. The column lands last on migrated DBs; all readers use column names.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"migrateVideos() rebuild (lines 277-399)\">\n**What changes:** a `hasLanguage` flag and a `languageExpr` (`\"language\"` or `\"NULL\"`); `language TEXT` in the `videos_new` CREATE; `language` in the INSERT and SELECT column lists.\n\n**What depends on it:** only very old crawl.db files that lack the error columns reach this rebuild.\n\n**Regression risk: low.** The column lists here are positional pairs, so an INSERT/SELECT that is out of step would silently shift data. Keep the three lists aligned.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"VideoUpsertRow (lines 465-491), VideoStore upsertStmt (1138-1196), upsertVideos (1453-1487)\">\n**What changes:** a `language: string | null` field. The INSERT column list gains `language`. The VALUES list grows from 25 to 26 `?`, and must stay aligned with `NULL, NULL, 0` for the error columns. The ON CONFLICT clause gains `language = excluded.language`, and the positional `run(...)` gains `row.language` at the matching position.\n\n**What depends on it:** `toVideoRow` builds the row.\n\n**Regression risk: medium.**\n- A positional mismatch between the column list, the `?` count and the `run()` arguments shifts every column after it. SQLite reports a count mismatch as an error, but not a mis-ordering.\n- **Behaviour:** `language = excluded.language` makes a re-crawl overwrite the stored language with NULL when the listing payload carries `{id: null}`. That is consistent with how the crawler treats `category`, but it differs from the handler's \"null keeps DB\" rule. A crawl can therefore erase a language the Engine learned. Only crawl.db is affected; whitelist.db is rebuilt from it by sync, see the sync entry.\n- `listExistingVideoIds` and `--new-videos` skip videos that already exist, so updater crawls never fill in `language` for existing rows. Existing rows get a language only from a full re-crawl or from `/api/video` views (whitelist.db only).\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"listVideosForTags / updateVideoTags / updateVideoInvalid / updateVideoError (lines 1283-1539)\">\n**What changes:** nothing.\n\n**What depends on it:** the tags enrichment writes only `tags_json`, so language is not touched.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"PeerTubeVideo interface (lines 84-118), new extractLanguage(), toVideoRow() (lines 648-709)\">\n**What changes:**\n- `PeerTubeVideo` gains `language?: PeerTubeLanguage | string`, where `PeerTubeLanguage` is `{ id?: string | null; label?: string }`, modelled on `PeerTubeCategory` at lines 78-82.\n- `extractLanguage`: an object gives `id` via `toNullableString`, a string gives itself via `toNullableString`, anything else gives `null`. It is placed next to `extractCategory` in the same style and carries a docstring comment.\n- `toVideoRow` sets `language: extractLanguage(video.language)`.\n\n**What depends on it:** `crawlChannelVideos` \u2192 `upsertVideos`. The PeerTube channel-videos listing does include `language`, so it is captured on the normal crawl path.\n\n**Regression risk: low.** Match the handler's rule exactly, including that a numeric id gives `null`. `toNullableString` rejects numbers, which is consistent with the handler using `pick_text`.\n</impact>\n<impact path=\"engine/crawler/dist/db.js\" element=\"compiled db module (VideoStore upsert line ~1100+, migrateVideos ~268, applyBaseSchema)\">\n**What changes:** regenerated by `npm run build` (`tsc -p tsconfig.json`) and committed with the source.\n\n**What depends on it:** production runs the dist, not the source. That covers `updater-worker.py` through `dist/videos-cli.js` (lines 952-982), `npm run crawl:*` and `run-dataset-build.sh`, plus `test_videos_worker.py`.\n\n**Regression risk: medium.** `test_videos_worker._dist_is_stale` compares only `videos-worker.ts` with `videos-worker.js`. A stale `db.js` is not caught by the staleness gate. It would show up only as `language` missing from the upsert (the new assertion) or as a superset-check failure later. Rebuild and commit both, and check the diff.\n</impact>\n<impact path=\"engine/crawler/dist/videos-worker.js\" element=\"compiled crawlVideos / toVideoRow / extractLanguage\">\n**What changes:** regenerated and committed.\n\n**What depends on it:** `test_videos_worker.py` imports it, and its staleness gate checks this pair.\n\n**Regression risk: medium, for the suite.** The rebuild needs `engine/crawler/node_modules` (typescript and better-sqlite3). `tsc` recompiles all of `src/`, so any other dist file already out of step (for example `host-filters.js`, which `test_host_normalisation.py` checks) will change in the same commit. Review the full dist diff.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"ensure_content_schema() CREATE TABLE videos (lines 350-383)\">\n**What changes:** `language TEXT` after `category`.\n\n**What depends on it:**\n- `main()` line 597 on every sync.\n- `test_repair_video_channel_names.py:70,134` builds its whitelist shape from this.\n- The new handler test and the migration test build from it.\n- `repair-video-channel-names.py` loads the module lazily.\n\n**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` does nothing on an existing whitelist.db, so the column on existing DBs comes only from the migration. The exact check then enforces it (next entry).\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"VIDEO_COLUMNS (line 96), ensure_schema_compatibility() (186-216), rebuild_content_tables() (448-522)\">\n**What changes:** nothing in code. `language` flows in from schema.sql.\n\n**Behaviour:**\n- The exact check (`VIDEO_COLUMNS + [\"popularity\"]`) rejects an unmigrated whitelist.db with \"missing columns: language ... Run migrate-whitelist.py\".\n- The superset check rejects a crawl.db the crawler has not opened with \"Update the crawl DB ...\".\n- The copy (`INSERT INTO videos (cols) SELECT cols FROM source.videos`) uses column names, so order does not matter.\n\n**Regression risk: medium (operational).**\n- `rebuild_content_tables` runs `DELETE FROM videos` and reloads from crawl.db. Every `/api/video` refresh in whitelist.db (tags, category, language, `last_checked_at`) is therefore thrown away on the next sync, unless the crawler has since stored the same values. The \"persisted\" metadata lasts only until the next dataset build. This is pre-existing for the other fields, and it now matters for `language` because crawl.db rarely has it for existing rows.\n- `scripts/run-dataset-build.sh:227-228` runs sync against an existing whitelist.db without migrating it first, so the first build after merge fails at the exact check until `migrate-whitelist.py` has run.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"VIDEOS_FTS_TRIGGERS_SQL / ensure_content_schema videos_fts (lines 270-417)\">\n**What changes:** nothing. The FTS index and the triggers cover `title, description, tags_json, category, channel_name`, not `language`, which is the plan's decision.\n\n**What depends on it:** the handler's UPDATE fires `videos_fts_au`.\n\n**Regression risk: none.** `ALTER TABLE ADD COLUMN` on `videos` leaves the triggers and the external-content FTS valid.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"migrate_videos_schema() rebuild (lines 232-370)\">\n**What changes:** it carries `language` conditionally, the same way the error columns are carried: `language TEXT` in `videos_new`, and `language` / `{language_expr}` in the INSERT and SELECT lists.\n\n**What depends on it:** `migrate_whitelist_schema`.\n\n**Regression risk: medium.** This rebuild also runs `DROP TABLE IF EXISTS video_embeddings` and drops `videos_fts` and its triggers (lines 262-266). A migration test whose inline legacy table lacks `last_error`, `last_error_at` or `error_count` takes this destructive path. Build the legacy fixture with the error columns present and only `language` missing, to test the additive path in isolation, or assert the rebuild path on purpose. As with db.ts, the positional lists must stay aligned.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"new migrate_videos_language(conn) and migrate_whitelist_schema() (lines 373-377)\">\n**What changes:** a new function. It returns early if the `videos` table does not exist (`_table_exists`); if `language` is not in `_columns(conn, \"videos\")` it runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is called last in `migrate_whitelist_schema`. Precedent: `recompute-popularity.ensure_popularity_schema` (lines 18-25) does the same kind of additive ALTER.\n\n**What depends on it:** `migrate-whitelist.py:87`, which runs inside `with conn:`.\n\n**Regression risk: low.** It is idempotent. The signature is `migrate_whitelist_schema(conn, table_name)`, so the test must pass `\"instances\"`. The FTS index is left alone: `videos_fts` is external content over named columns.\n</impact>\n<impact path=\"engine/server/db/jobs/migrate-whitelist.py\" element=\"main() (lines 72-91)\">\n**What changes:** nothing in code. It now also adds `language`.\n\n**What depends on it:** the operator runbook. It must run on every whitelist.db (prod, dev, the one symlinked into worktrees) before the new Engine starts. It takes a backup by default (a full file copy of a large DB).\n\n**Regression risk: low (code), high (process).** The step is manual, and forgetting it breaks `/api/video` everywhere and makes `sync-whitelist` refuse to run. It imports `server.db.jobs.whitelist_migrations` with `engine_dir` on the path.\n</impact>\n<impact path=\"engine/server/db/jobs/merge-staging-db.py\" element=\"merge column intersection (lines 142-158) with merge_rules.json videos INSERT_ONLY\">\n**What changes:** nothing.\n\n**Behaviour:** `merge_columns = [c for c in prod_columns if c in stage_columns]`. Staging is created from schema.sql and has `language`. If prod is unmigrated, `language` is silently dropped from the merged new rows, with no error. Because `videos` is INSERT_ONLY, existing prod rows never receive `language` from the updater.\n\n**What depends on it:** the updater cycle.\n\n**Regression risk: low.** It fails soft. It is one more reason to migrate prod first. The plan says \"updater-worker merges through shared_columns\"; the merge that matters is in `merge-staging-db.py`, and `shared_columns` in the updater only seeds `channels`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"init_staging_db (548-565), seed_staging_from_prod / shared_columns (568-619), crawler dist invocation (952-982)\">\n**What changes:** nothing.\n\n**What depends on it:** staging is created from the new schema.sql. The crawler dist, once rebuilt, writes `language` to staging. The updater restarts the Engine after the merge. If prod whitelist.db is not migrated by then, the restarted Engine serves broken `/api/video`.\n\n**Regression risk: low (code), medium (process).**\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"parse_tags / build_text (lines 19-54), queries (187-205)\">\n**What changes:** nothing. It reads `tags_json` and `category` by name, and not `language`.\n\n**Regression risk: none.** `\"[]\"` parses to no tags. Embeddings are not recomputed on refresh; that is the plan's accepted staleness.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"FTS lexical query / row projection (lines 60-70)\">\n**What changes:** nothing. It uses explicit columns.\n\n**Regression risk: none.** It reflects refreshed tags and category through the triggers.\n</impact>\n<impact path=\"engine/server/db/jobs/repair-video-channel-names.py\" element=\"lazy load of sync-whitelist.py\">\n**What changes:** nothing.\n\n**What depends on it:** it loads `sync-whitelist.py`, which parses schema.sql at import. Its UPDATE touches only `channel_name`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"create_table_and_indexes_from_source / copy_and_prune_prod (lines 198-340)\">\n**What changes:** nothing. It copies the table DDL from the source DB and then runs `INSERT ... SELECT *`, so the shapes always match.\n\n**Regression risk: low.** If the source prod is unmigrated, the mini-prod lacks `language`, and the merge silently drops it (see the merge entry).\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"hand-written CREATE TABLE videos (line 157)\">\n**What changes:** nothing. It never calls `fetch_video_row` or the sync schema checks.\n\n**Regression risk: none.** Listed so nobody \"fixes\" it.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture on WHITELIST_DB (lines 34, 105-145); sys.path with client/backend first (37-43)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- **Engine fixture.** The session Engine runs on the worktree's `engine/server/db/whitelist.db`, which is shared with main. No `tests/active` file calls `/api/video` (grep), so the suite stays green on an unmigrated DB, but a manual or smoke run does not.\n- **Imports in the new handler test.** `handlers.video` does `from http_utils import respond_json`. `client/backend` holds only `server.py` and `lib/`, so a top-level `http_utils` resolves to `engine/server/api/http_utils.py` once that is on `sys.path`. `server` is already cached as the Client module, and `video.py` does not import `server`.\n\n**Regression risk: low.** Do not make the Engine migrate the DB at startup (plan decision): that would ALTER the shared DB from a worktree run.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_video_proxy check (line 582)\">\n**What changes:** nothing.\n\n**What depends on it:** it expects `/api/video` to answer 200 through the Client on the live whitelist.db.\n\n**Regression risk: medium.** It fails until `migrate-whitelist.py` has run on that DB. `tests/run-installers-smoke.sh:647` has the same check, with `|| true`, so it only reports.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"stages crawl:videos:tags (215) \u2192 sync-whitelist (227-228)\">\n**What changes:** nothing.\n\n**What depends on it:** the tags stage opens crawl.db through `VideoStore`, so the additive crawler migration runs automatically. The sync stage then fails on an unmigrated existing whitelist.db.\n\n**Regression risk: medium (operational).** The runbook, or the script, needs a `migrate-whitelist.py` step before sync. Adding it to the script is outside the plan; document it.\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"player-info block between video-meta-row (68-95) and video-description (96)\">\n**What changes:** a new `video-taxonomy` block with category and language spans and a tags container.\n\n**What depends on it:** `index.ts` looks the elements up by id at module top (lines 22-48 pattern).\n\n**Constraints:**\n- The CSP (line 8) has `style-src 'self'`, so there are no inline `style=` attributes. Hide elements with the `hidden` attribute or a class.\n- Use a semantic list or `role` for the chips, and an `aria-label` for the tags region.\n\n**Regression risk: low.**\n- Issue 14 (collapsible description) edits the adjacent `video-description` markup, CSS and fill code, so a merge conflict is likely if both are open.\n- `client/frontend/dist/video-page.html` is the built copy (see the dist entry).\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"VideoMetadata type (481-501), fetchVideoMetadataFromServer (517-555), fetchVideoMetadataFromInstance (560-625), loadVideo (85-229), element lookups (22-48)\">\n**What changes:**\n- `VideoMetadata` gains `tags`, `category` and `language`.\n- The server path reads `data.tags` (array filtered to strings), `data.category` and `data.language`, with `\"\"` or `[]` defaults.\n- The instance path reads `data.tags`, `(data.category as {label}).label` and `(data.language as {label}).label`, with type guards because the payload is `Record<string, unknown>`.\n- `loadVideo` renders with `textContent` and `createElement` / `replaceChildren` for the chips.\n\n**Details to get right:**\n- **Null metadata.** When both fetches fail, `metadata` is `null`. The block should then be hidden, or show \"No tags\", consistently. Decide which.\n- **\"Unknown\" asymmetry.** For an unset language, PeerTube sends `{id: null, label: \"Unknown\"}`. The server path hides it: the stored value is NULL, which becomes `\"\"`. The instance fallback shows \"Unknown\" through `language.label`, so the two paths disagree. Treat a null `id` as empty on the instance path too, or accept the difference and document it.\n- **Category \"Unknown\".** It shows on both paths.\n- **Existing HTML interpolation.** Existing rendering uses `innerHTML` with `escapeHtml` elsewhere. The new code must not interpolate tags into `innerHTML`.\n\n**Regression risk: low.** `fetchVideoMetadataFromServer` returns null on `!response.ok`, which already covers the 502 case.\n</impact>\n<impact path=\"client/frontend/src/video.css\" element=\"new .video-taxonomy / chip styles near .video-meta-row (309-347) and .metric (325-332)\">\n**What changes:** compact label and chip rules that reuse `--line`, `--muted`, `--accent-strong`, the `rgba(180, 87, 55, 0.08)` background, `border-radius: 999px` and 0.8\u20130.9rem font sizes.\n\n**Gotcha:** an author `display:` rule overrides the UA `[hidden]{display:none}`. `.instance-meta` (`display: inline-flex`) already has this latent bug. If the new spans get `display: inline-flex` or `flex`, add an explicit `.video-taxonomy [hidden] { display: none; }` or equivalent, or `hidden = true` will not hide them. The existing `:empty` pattern (lines 304-307) is an alternative.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/dist\" element=\"committed build output: video-page.html, assets/video-*.js, assets/video-*.css\">\n**What changes:** a rebuild with `vite build` (`npm run build`). The hashed asset names change, `dist/video-page.html` references the new names, and the old `video-gjYm1MC8.js` and `video-ypOuFwNw.css` become orphans to delete. Shared chunks may be re-hashed too.\n\n**What depends on it:** production serving. DEPLOYMENT.md:301 says to re-run the rsync after every build.\n\n**Regression risk: low.** Commit a consistent set. No `tests/active` test reads the dist; the frontend tests bundle `src` with esbuild.\n</impact>\n<impact path=\"tests/active/test_video_handler.py\" element=\"new test module (handler, labels, migration)\">\n**What changes:** a new file.\n\n**Imports:**\n- It loads `sync-whitelist.py` through `importlib.util.spec_from_file_location`, under a unique module name. `test_repair_video_channel_names.py` uses `sync_whitelist_channel_names` and `test_host_normalisation` uses `sync_whitelist_job`.\n- It inserts `engine/server` and `engine/server/api` into `sys.path` and does `from handlers import video`. This works in-process, as `test_internal_events.py:37` does: `video.py` imports no numpy or faiss (`data.time`, `data.popularity`, `http_utils`).\n\n**Fixture DB:**\n- A `tmp_path` DB with `ensure_whitelist_schema` + `ensure_content_schema`, and `row_factory = sqlite3.Row`, so that `dict(row)` works.\n- `videos` needs `last_checked_at` (NOT NULL). `instances` needs `last_error`, `last_error_at` and `last_error_source` set to non-NULL for the failure assertions.\n- A `channels` row with a matching `channel_id`.\n\n**Stand-in server:** `db`, `db_lock` (`threading.Lock`), `video_error_threshold` and `popularity_like_weight`.\n\n**Monkeypatch targets:** `video.respond_json`, `video.fetch_instance_json` (path-keyed), and `video.urlopen` for the parse-guard cases. The fake response must support `with`, `.status` and `.read()`.\n\n**Assertions:**\n- Whole-row `SELECT *` snapshots before and after, for failure.\n- `last_checked_at` is strictly greater than a seeded old value. Seed it well in the past, not with `now_ms()`, to avoid equal-millisecond flakes.\n\n**Regression risk: low for production, medium for suite stability.**\n- It must never use the `engine`/`dataset` fixtures or `WHITELIST_DB`.\n- A `urlopen` fake that raises `URLError` checks the kept network contract.\n- A `channel` in the payload triggers a second `fetch_instance_json` call, so the path-keyed fake must answer `/api/v1/video-channels/...` or return `None`.\n</impact>\n<impact path=\"tests/active/test_videos_worker.py\" element=\"test_crawl_writes_each_hosts_own_channel_name and a new additive-migration case\">\n**What changes:**\n- The alpha payload items gain `language: {id: \"en\", label: \"English\"}`, and the SELECT and assertion include `language`.\n- A second case pre-creates crawl.db with the old videos DDL. It has to be written inline, because schema.sql will already contain `language`. It then runs `crawlVideos` and asserts the column exists and is filled.\n\n**What depends on it:**\n- node on PATH, `engine/crawler/node_modules` (better-sqlite3) and a fresh dist.\n- The `_dist_is_stale` gate covers only the `videos-worker` pair.\n- The test builds its DB with `conn.executescript(SCHEMA...)`, so the new-schema case never exercises the ALTER. The second case is the one that proves the migration.\n\n**Regression risk: medium.** The node, dist and node_modules requirements are hard, and missing ones fail rather than skip. Keep one test per claim, and keep the module docstring bullets in the file's style.\n</impact>\n<impact path=\"tests/active/test_repair_video_channel_names.py\" element=\"crawl/whitelist fixtures built from schema.sql and ensure_content_schema\">\n**What changes:** nothing. The inserts name their columns, and the new nullable column is harmless.\n\n**What depends on it:** it is the precedent for the `_load_job` loader the new test copies.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"dist staleness gate for host-filters (_dist_is_stale)\">\n**What changes:** nothing.\n\n**Regression risk: low.** `npm run build` rewrites every dist file. If `host-filters.js` changes, commit it; by commit time it is then newer, not stale.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (lines 133-139)\">\n**What changes:** at harvest:\n- Map `test_video_handler.py` to `engine/server/api/handlers/video.py`, `engine/server/data/peertube_labels.py`, `engine/server/db/jobs/whitelist_migrations.py` and `engine/server/db/jobs/sync-whitelist.py`.\n- Extend `test_videos_worker.py`'s entry with `engine/crawler/src/db.ts`, `engine/crawler/dist/db.js` and `engine/crawler/schema.sql`. Today it lists only the videos-worker pair, so a `db.ts`-only change would not re-run it.\n\n**Regression risk: low.** The file is local and gitignored.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked test record (and tests/last_test_output.txt)\">\n**What changes:** both are regenerated by `validate_tests.py`.\n\n**Regression risk: none functionally.** They conflict on merge: take main's copy and re-run with `--compare`.\n</impact>\n</impacts>\n",
  "docs_checklist": "- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md: added `videos.language` to the crawl and sync sections, plus the schema checks and upgrade order for sync.\n- [x] `engine/server/README.md` - updated: I rewrote the `/api/video` bullet in `engine/server/README.md` so it describes what the route does now: it refreshes from the source instance, writes to the DB only when the fetch succeeds, returns six new keys, shows category and language as labels, and needs the `language` migration.\n- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: `/api/video` write-back conditions, a whitelist migration note, and a Triage row for an unmigrated `whitelist.db`\n- [x] `docs/project/roadmap.md` - updated: roadmap.md: rewrote Implementation-order step 2 (Language) around what remains now that language capture is in, and fixed the stale feed-panel plan path.\n- [x] `docs/project/plans/archive/04-feed-parameter-panel.md` - updated: Recorded in the plan that I1's language column and crawler capture already exist, as `language` (the code only, no label column), so a later I1 build won't add `language_id`/`language_label` twice.\n- [x] `docs/project/plans/18-english-subtitles.md` - updated: Corrected the three statements in the subtitles plan that said the `videos` table has no language column.\n- [x] `docs/project/issues/10-video-metadata-completeness.md` - updated: Closed issue 10 as delivered: the status is now `enhancement, complete`, a Delivered comment lists the accepted limits, and the file is written to `docs/project/issues/archive/`. The original at `docs/project/issues/10-video-metadata-completeness.md` is still there because I have no tool that can delete a file. Please `git rm` it.\n- [x] `docs/project/issues/14-collapsible-description.md` - out of scope: Nothing it claims is false. It describes the `video-description` behaviour, which this build did not change. The new `video-taxonomy` block between `video-meta-row` and `video-description` only affects merges: expect a conflict at harvest when both touch the adjacent markup, CSS and `loadVideo` fill code. That is a note for the merge, not a document edit.\n- [x] `README.md` - out of scope: It mentions `/api/video` only as a public route (line 46-48) and as a smoke check expecting 200 through the Client proxy (line 134). Both are still true once the whitelist DB is migrated. It says nothing about what the route returns or refreshes.\n- [x] `client/README.md` - out of scope: It lists `/api/video` only as a read-gateway route (line 37). The proxy still passes the body through unchanged, so the line stays accurate.\n- [x] `client/frontend/README.md` - out of scope: It says the frontend fetches `/api/video` and renders the video page (lines 8-9), without listing which metadata the page shows. Nothing there is made false by the new taxonomy block.",
  "docs": [
    {
      "path": "DATA_BUILD.md",
      "note": "Sections 1 and 2:\n- Add a note that the crawler adds `videos.language` (the PeerTube language code) to an existing `crawl.db` the first time any crawler command opens it.\n- Add a note that `sync-whitelist.py` refuses a `crawl.db` the crawler has not opened yet (superset check).\n- Add a note that `sync-whitelist.py` refuses an existing `whitelist.db` until `migrate-whitelist.py` has added the column.\n- Beside the existing `migrate-whitelist.py` block (lines 155-158), add the upgrade order: merge; open or run the crawler once on `crawl.db`; run `migrate-whitelist.py` on every `whitelist.db`, prod included; then restart the Engine.\n\nTwo notes for step 2:\n- `run-dataset-build.sh` does not migrate on its own.\n- Refreshes made by `/api/video` in `whitelist.db` are replaced by the next sync."
    },
    {
      "path": "engine/server/README.md",
      "note": "Line 9 (`/api/video`) should describe:\n- **Refresh.** One source fetch refreshes and persists title, description, stats, tags, category, language, nsfw, duration and thumbnail.\n- **Failure.** A failed or malformed source leaves the DB untouched and answers from the DB.\n- **Response keys.** The new keys are `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Category and language are mapped to PeerTube default labels.\n- **Migration.** The whitelist DB must be migrated (`language` column)."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "**Line 374:** optionally note that `/api/video` writes back to `whitelist.db` only when the source answers inside the request's statement budget.\n\n**Upgrade notes:** add a short note, or a Triage row, for this deploy:\n- Before restarting the Engine, run `migrate-whitelist.py` on the Engine's `whitelist.db`.\n- Symptom when it is skipped: every video page falls back to direct-instance metadata. The Client proxy logs 502 `ENGINE_PROXY_UNAVAILABLE` on `/api/video`, and the Engine journal shows `no such column: v.language`."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Implementation-order step 2 (line 142) refers to feed-panel I1 language capture.\n- This build already captures `videos.language` (the code), so I1 is partly delivered under a different column name than plan 04 proposes.\n- Update the step so it names what remains: label storage if needed, backfill I3, and the filter I2.\n- Note that existing rows get a language only from a full re-crawl or from video-page views."
    },
    {
      "path": "docs/project/plans/archive/04-feed-parameter-panel.md",
      "note": "I1 (lines 19-20, 47-48) specifies `language_id` + `language_label`. Record, or link from the roadmap, that `language` (code only) now exists and that labels resolve at read time through `engine/server/data/peertube_labels.py`, so that I1 does not add a duplicate column."
    },
    {
      "path": "docs/project/plans/18-english-subtitles.md",
      "note": "Lines 20, 43 and 90 say the `videos` table stores no language and that there is \"no language column to select by\". After this build both statements are false. Update them, noting that coverage is sparse for existing rows."
    },
    {
      "path": "docs/project/issues/10-video-metadata-completeness.md",
      "note": "At harvest on main, not in this worktree:\n- Set `Status: enhancement, complete` and append a delivery comment.\n- Record the accepted limits: default-only labels; \"Unknown\" category; removals of language and description are not propagated; persistence is best-effort under the 5 s statement deadline; refreshes are lost at the next sync.\n- Move the file to `docs/project/issues/archive/`."
    },
    {
      "path": "docs/project/issues/14-collapsible-description.md",
      "note": "No content change is needed. Note at harvest that the video page now has a taxonomy block between `video-meta-row` and `video-description`. Issue 14 edits the adjacent markup, CSS and fill code, so expect a merge conflict."
    }
  ],
  "reassessments": 1,
  "draft": "\n# Draft implementation: issue 10, video metadata completeness\n\nI read every file this touches before drafting: `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, `schema.sql`, `db.ts`, `videos-worker.ts`, `video-page.html`, `index.ts`, `video.css`, `test_videos_worker.py`, `test_repair_video_channel_names.py` and `test_internal_events.py`. New code copies each file's own style: one-line docstrings or `/** Handle \u2026 */` blocks, the `has_x`/`x_expr` rebuild pattern, `pick_*` helpers, and bulleted test-module docstrings.\n\nThe step's ladder placeholder (`{rat_tail_ladder}`) arrived unrendered. This draft is therefore written against R1\u2013R7, the plan and the settled impact inventory.\n\n## What has to be testable (ladder rung 1)\n\n| Claim | Where it is proven |\n|---|---|\n| Success writes all R2 fields, bumps `last_checked_at`, resets `instances.last_error*`, and returns the R5 keys | `test_video_handler.py::test_success_refreshes_row_and_response` |\n| A caught network error (stub `None`, and real `urlopen` raising `URLError`) writes nothing and answers from the DB | `test_fetch_failure_leaves_db_untouched[stub-none, urlopen-urlerror]` |\n| A malformed body (not JSON, bad UTF-8, a JSON list) writes nothing | `test_fetch_failure_leaves_db_untouched[not-json, bad-utf8, json-list]` |\n| A partial payload keeps the stored tags and category | `test_partial_payload_keeps_tags_and_category` |\n| `tags: []` stores `\"[]\"` and returns `[]` | `test_empty_tag_list_propagates` |\n| A source change between two requests is reflected in the DB and the response | `test_second_request_reflects_source_change` |\n| Labels: `\"15\"` gives the label, an unknown id stays raw, a text category passes through, a language code gives its label, an unknown code stays raw | `test_response_labels` (parametrised, DB-only path) |\n| The whitelist migration adds `language`, keeps rows and FTS triggers, and is idempotent | `test_migration_adds_language_column` |\n| The crawler persists `language` | `test_videos_worker.py::test_crawl_writes_each_hosts_own_channel_name` (extended) |\n| The crawler adds `language` to an old crawl.db | `test_videos_worker.py::test_crawl_adds_language_to_existing_db` |\n\n## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/handlers/video.py` | Parse guard, `None` success signal, new extractors, one merge, a write only on success, new response keys |\n| `engine/server/data/peertube_labels.py` | **new**: `CATEGORY_LABELS`, `LANGUAGE_LABELS`, `category_label`, `language_label` |\n| `engine/server/db/jobs/whitelist_migrations.py` | `migrate_videos_language`; the rebuild carries `language` |\n| `engine/server/db/jobs/sync-whitelist.py` | `language TEXT` in `ensure_content_schema` |\n| `engine/crawler/schema.sql` | `language TEXT` after `category` (no index) |\n| `engine/crawler/src/db.ts` | `migrateVideosLanguage`; the rebuild carries `language`; `VideoUpsertRow.language`; the upsert |\n| `engine/crawler/src/videos-worker.ts` | `PeerTubeLanguage`, `extractLanguage`, `toVideoRow.language` |\n| `engine/crawler/dist/*.js` | `npm run build`, commit every changed dist file |\n| `client/frontend/video-page.html` | `video-taxonomy` block |\n| `client/frontend/src/pages/video-page/index.ts` | Type, both fetch paths, `renderTaxonomy` |\n| `client/frontend/src/video.css` | Taxonomy and chip styles |\n| `client/frontend/dist` | `npm run build`; delete orphaned hashed assets |\n| `tests/active/test_video_handler.py` | **new** |\n| `tests/active/test_videos_worker.py` | Extended, plus one new case |\n\nUnchanged on purpose: `client/backend/server.py` (it passes the body through), `similar.py`, `updater-worker.py`, `merge-staging-db.py` and `build-video-embeddings.py`.\n\n---\n\n## 1. `engine/server/api/handlers/video.py`\n\n### Imports\n```python\nfrom data.time import now_ms\nfrom data.popularity import compute_popularity\nfrom data.peertube_labels import category_label, language_label\nfrom http_utils import respond_json\n```\n\n### `fetch_video_row`\nThe SELECT list gains three lines after `v.nsfw`:\n```sql\n          v.nsfw,\n          v.language,\n          v.duration,\n          v.thumbnail_url,\n          v.last_checked_at,\n```\n\n### `fetch_instance_json`\nInvariant: it returns a `dict`, or `None`. It never raises for network, HTTP, decode or parse failures. The `# pragma: no cover` comes off because the tests now cover this branch.\n```python\ndef fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:\n    \"\"\"Fetch a JSON object from a PeerTube instance API path; None on network failure, non-200, a malformed body or a non-object body.\"\"\"\n    url = f\"https://{host}{path}\"\n    req = Request(url, headers={\"accept\": \"application/json\"})\n    try:\n        with urlopen(req, timeout=8) as resp:\n            if resp.status != 200:\n                return None\n            data = json.loads(resp.read().decode(\"utf-8\"))\n    except (HTTPError, URLError, TimeoutError) as exc:\n        logging.info(\"[video] instance request failed: %s\", exc)\n        return None\n    except ValueError as exc:\n        # UnicodeDecodeError and JSONDecodeError are both ValueError.\n        logging.info(\"[video] instance response is not valid JSON: host=%s path=%s: %s\", host, path, exc)\n        return None\n    if not isinstance(data, dict):\n        logging.info(\"[video] instance response is not a JSON object: host=%s path=%s\", host, path)\n        return None\n    return data\n```\n\n### New and changed helpers (placed next to the existing ones)\n```python\ndef pick_present(value: Any, fallback: Any) -> Any:\n    \"\"\"Return value unless it is None, else fallback (source-over-DB merge rule).\"\"\"\n    return fallback if value is None else value\n\n\ndef id_text(value: Any) -> str | None:\n    \"\"\"Normalize a PeerTube id to text: a non-empty trimmed string or an int (never a bool); None otherwise.\"\"\"\n    if isinstance(value, bool):\n        return None\n    if isinstance(value, int):\n        return str(value)\n    return pick_text(value)\n\n\ndef to_tags_json(value: Any) -> str | None:\n    \"\"\"Convert a tag list to a JSON array of its string elements (\"[]\" when there are none); None when the value is not a list.\"\"\"\n    if isinstance(value, list):\n        return json.dumps([tag for tag in value if isinstance(tag, str)], ensure_ascii=False)\n    return None\n\n\ndef extract_category(value: Any) -> str | None:\n    \"\"\"Extract the category label/name, else its id as text; a plain string or int is kept as text; None when absent or empty.\"\"\"\n    if isinstance(value, dict):\n        return pick_text(value.get(\"label\"), value.get(\"name\")) or id_text(value.get(\"id\"))\n    return id_text(value)\n\n\ndef extract_language(value: Any) -> str | None:\n    \"\"\"Extract the PeerTube language code: an object's id or a plain non-empty string; None for a null id or anything else.\"\"\"\n    if isinstance(value, dict):\n        return pick_text(value.get(\"id\"))\n    return pick_text(value)\n\n\ndef tags_from_json(value: Any) -> list[str]:\n    \"\"\"Parse stored tags_json into its string tags; [] when null, empty, invalid or not a list.\"\"\"\n    if not isinstance(value, str) or not value:\n        return []\n    try:\n        parsed = json.loads(value)\n    except ValueError:\n        return []\n    if not isinstance(parsed, list):\n        return []\n    return [tag for tag in parsed if isinstance(tag, str)]\n```\n\nDecisions:\n- **`ensure_ascii=False`.** Refreshed tags are stored as raw UTF-8, the same as the crawler's `JSON.stringify`, so FTS indexes the words rather than `\\uXXXX` escapes. This resolves the judgment call the `to_tags_json` inventory entry left open.\n- **`extract_category` with a plain string.** It now goes through `pick_text`, so `\"\"` or whitespace keeps the DB value (the gap the inventory found).\n- **Integer ids only.** Floats and bools are rejected; PeerTube category ids are integers.\n\n### `fetch_instance_video_dynamic`\nInvariant: `None` exactly when the detail fetch gave no dict (R1). Otherwise a dict in which `None` always means \"keep the DB value\".\n```python\ndef fetch_instance_video_dynamic(host: str, video_id: str) -> dict[str, Any] | None:\n    \"\"\"Fetch live video metadata from instance and normalize fields; None when the video detail fetch fails (the single success signal).\"\"\"\n    detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\")\n    if detail is None:\n        return None\n    account = detail.get(\"account\")\n    if not isinstance(account, dict):\n        account = {}\n    channel = detail.get(\"channel\")\n    if not isinstance(channel, dict):\n        channel = {}\n    channel_slug = pick_text(channel.get(\"name\"))\n    # ... channel_display / channel_followers / channel_detail block unchanged ...\n    return {\n        \"title\": pick_text(detail.get(\"name\"), detail.get(\"title\")),\n        \"description\": pick_text(detail.get(\"description\")),\n        \"views\": ...,  # unchanged\n        \"likes\": ...,  # unchanged\n        \"dislikes\": ...,  # unchanged\n        \"tags_json\": to_tags_json(detail.get(\"tags\")),\n        \"category\": extract_category(detail.get(\"category\")),\n        \"language\": extract_language(detail.get(\"language\")),\n        \"nsfw\": to_nullable_bool(detail.get(\"nsfw\")),\n        \"duration\": pick_number(detail.get(\"duration\")),\n        \"thumbnail_url\": resolve_asset_url(host, pick_text(detail.get(\"thumbnailUrl\"), detail.get(\"thumbnailPath\"))) or None,\n        # channel_slug, channel_display, channel_followers, account_* unchanged\n    }\n```\nThe `or None` on `thumbnail_url` is there because `resolve_asset_url` returns `\"\"` for a missing value. Without it, a missing thumbnail would overwrite the stored one with `\"\"`.\n\n### `handle_video_request`: merge, response, write\n```python\n    instance_domain = row.get(\"instance_domain\") or host_param or \"\"\n    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else None\n    # One merged value set feeds both the response and the UPDATE; on failure `source` is empty, so every field is the DB value.\n    source = dynamic if dynamic is not None else {}\n\n    title = source.get(\"title\") or row.get(\"title\")\n    description = source.get(\"description\") or row.get(\"description\")\n    views = pick_present(source.get(\"views\"), row.get(\"views\"))\n    likes = pick_present(source.get(\"likes\"), row.get(\"likes\"))\n    dislikes = pick_present(source.get(\"dislikes\"), row.get(\"dislikes\"))\n    channel_display = source.get(\"channel_display\") or row.get(\"channel_display_name\") or row.get(\"channel_name\")\n    channel_slug = source.get(\"channel_slug\") or row.get(\"channel_slug\")\n    channel_followers = pick_present(source.get(\"channel_followers\"), row.get(\"channel_followers_count\"))\n    tags_json = pick_present(source.get(\"tags_json\"), row.get(\"tags_json\"))\n    category = pick_present(source.get(\"category\"), row.get(\"category\"))\n    language = pick_present(source.get(\"language\"), row.get(\"language\"))\n    nsfw = pick_present(source.get(\"nsfw\"), row.get(\"nsfw\"))\n    duration = pick_present(source.get(\"duration\"), row.get(\"duration\"))\n    thumbnail_url = pick_present(source.get(\"thumbnail_url\"), row.get(\"thumbnail_url\"))\n```\nThe `channel_url`, `embed_url` and `original_url` code is unchanged.\n\nThe response keeps all 18 keys; `\"accountAvatarUrl\": source.get(\"account_avatar_url\") or \"\"` replaces `dynamic.get(...)`. Six keys are appended:\n```python\n        \"tags\": tags_from_json(tags_json),\n        \"category\": category_label(category),\n        \"language\": language_label(language),\n        \"nsfw\": None if nsfw is None else bool(nsfw),\n        \"duration\": pick_number(duration),\n        \"thumbnailUrl\": thumbnail_url or \"\",\n```\n\nWrite block: the guard becomes `if dynamic is not None and instance_domain and row.get(\"video_id\"):` and it tests identity, not truthiness. The UPDATE becomes:\n```sql\nUPDATE videos\nSET title = ?, description = ?, channel_name = ?, views = ?, likes = ?, dislikes = ?,\n    popularity = ?,\n    tags_json = ?, category = ?, language = ?, nsfw = ?, duration = ?, thumbnail_url = ?, last_checked_at = ?\nWHERE video_id = ? AND instance_domain = ?\n```\nThe parameter tuple is extended in the same order: `\u2026, tags_json, category, language, nsfw, duration, thumbnail_url, checked_at, video_id, instance_domain`. The `channels` UPDATE, the `instances` reset, the transaction and the `OperationalError` catch are unchanged.\n\nInvariant: on failure no statement runs, so `last_checked_at`, `channels` and `instances.last_error*` stay exactly as they were.\n\nPre-existing issue, flagged and not changed: on success with no channel slug anywhere, the `channels` UPDATE writes `channel_name = NULL`.\n\n---\n\n## 2. `engine/server/data/peertube_labels.py` (new)\n```python\n\"\"\"PeerTube default video category and language labels.\n\nResponsibilities:\n- Map PeerTube's stock category ids and language codes to display labels for /api/video.\n- Leave unknown ids and codes raw (named simplification: plugin-added or renamed entries are not covered; upgrade path is caching each instance's /api/v1/videos/categories and /api/v1/videos/languages).\n\"\"\"\nfrom __future__ import annotations\n\nCATEGORY_LABELS: dict[str, str] = {\n    \"1\": \"Music\", \"2\": \"Films\", \"3\": \"Vehicles\", \"4\": \"Art\", \"5\": \"Sports\", \"6\": \"Travels\", \"7\": \"Gaming\", \"8\": \"People\", \"9\": \"Comedy\",\n    \"10\": \"Entertainment\", \"11\": \"News & Politics\", \"12\": \"How To\", \"13\": \"Education\", \"14\": \"Activism\", \"15\": \"Science & Technology\", \"16\": \"Animals\", \"17\": \"Kids\", \"18\": \"Food\",\n}\n\nLANGUAGE_LABELS: dict[str, str] = { ... }  # see below\n\n\ndef category_label(value: str | None) -> str:\n    \"\"\"Return the display label for a stored category: a digit-only id resolves through the default map, anything else (or an unknown id) is returned as is; \"\" when empty.\"\"\"\n    if not isinstance(value, str) or not value:\n        return \"\"\n    if value.isascii() and value.isdigit():\n        return CATEGORY_LABELS.get(value, value)\n    return value\n\n\ndef language_label(value: str | None) -> str:\n    \"\"\"Return the display label for a stored language code (case-sensitive); an unknown code is returned raw; \"\" when empty.\"\"\"\n    if not isinstance(value, str) or not value:\n        return \"\"\n    return LANGUAGE_LABELS.get(value, value)\n```\n\n**`LANGUAGE_LABELS` contents.** This is PeerTube's `buildLanguages()` output: living ISO 639-1 languages keyed by their 639-1 code, plus the extra 639-3 set, keyed by the 639-3 code, including the sign languages. The draft literal below was written from memory. Before commit, the implementation step **must replace it wholesale** with the JSON from a stock instance's `GET /api/v1/videos/languages`, pasted as a literal. This is the \"copied once\" step in the plan, and it removes the fidelity risk rather than accepting it.\n```python\nLANGUAGE_LABELS: dict[str, str] = {\n    \"aa\": \"Afar\", \"ab\": \"Abkhazian\", \"af\": \"Afrikaans\", \"ak\": \"Akan\", \"am\": \"Amharic\", \"an\": \"Aragonese\", \"ar\": \"Arabic\", \"as\": \"Assamese\", \"av\": \"Avaric\", \"ay\": \"Aymara\", \"az\": \"Azerbaijani\",\n    \"ba\": \"Bashkir\", \"be\": \"Belarusian\", \"bg\": \"Bulgarian\", \"bi\": \"Bislama\", \"bm\": \"Bambara\", \"bn\": \"Bengali\", \"bo\": \"Tibetan\", \"br\": \"Breton\", \"bs\": \"Bosnian\",\n    \"ca\": \"Catalan\", \"ce\": \"Chechen\", \"ch\": \"Chamorro\", \"co\": \"Corsican\", \"cr\": \"Cree\", \"cs\": \"Czech\", \"cv\": \"Chuvash\", \"cy\": \"Welsh\",\n    \"da\": \"Danish\", \"de\": \"German\", \"dv\": \"Dhivehi\", \"dz\": \"Dzongkha\", \"ee\": \"Ewe\", \"el\": \"Greek\", \"en\": \"English\", \"eo\": \"Esperanto\", \"es\": \"Spanish\", \"et\": \"Estonian\", \"eu\": \"Basque\",\n    \"fa\": \"Persian\", \"ff\": \"Fulah\", \"fi\": \"Finnish\", \"fj\": \"Fijian\", \"fo\": \"Faroese\", \"fr\": \"French\", \"fy\": \"Western Frisian\",\n    \"ga\": \"Irish\", \"gd\": \"Scottish Gaelic\", \"gl\": \"Galician\", \"gn\": \"Guarani\", \"gu\": \"Gujarati\", \"gv\": \"Manx\",\n    \"ha\": \"Hausa\", \"he\": \"Hebrew\", \"hi\": \"Hindi\", \"ho\": \"Hiri Motu\", \"hr\": \"Croatian\", \"ht\": \"Haitian\", \"hu\": \"Hungarian\", \"hy\": \"Armenian\", \"hz\": \"Herero\",\n    \"id\": \"Indonesian\", \"ig\": \"Igbo\", \"ii\": \"Sichuan Yi\", \"ik\": \"Inupiaq\", \"is\": \"Icelandic\", \"it\": \"Italian\", \"iu\": \"Inuktitut\",\n    \"ja\": \"Japanese\", \"jv\": \"Javanese\", \"ka\": \"Georgian\", \"kg\": \"Kongo\", \"ki\": \"Kikuyu\", \"kj\": \"Kuanyama\", \"kk\": \"Kazakh\", \"kl\": \"Kalaallisut\", \"km\": \"Central Khmer\", \"kn\": \"Kannada\", \"ko\": \"Korean\", \"kr\": \"Kanuri\", \"ks\": \"Kashmiri\", \"ku\": \"Kurdish\", \"kv\": \"Komi\", \"kw\": \"Cornish\", \"ky\": \"Kirghiz\",\n    \"la\": \"Latin\", \"lb\": \"Luxembourgish\", \"lg\": \"Ganda\", \"li\": \"Limburgan\", \"ln\": \"Lingala\", \"lo\": \"Lao\", \"lt\": \"Lithuanian\", \"lu\": \"Luba-Katanga\", \"lv\": \"Latvian\",\n    \"mg\": \"Malagasy\", \"mh\": \"Marshallese\", \"mi\": \"Maori\", \"mk\": \"Macedonian\", \"ml\": \"Malayalam\", \"mn\": \"Mongolian\", \"mr\": \"Marathi\", \"ms\": \"Malay\", \"mt\": \"Maltese\", \"my\": \"Burmese\",\n    \"na\": \"Nauru\", \"nb\": \"Norwegian Bokm\u00e5l\", \"nd\": \"North Ndebele\", \"ne\": \"Nepali\", \"ng\": \"Ndonga\", \"nl\": \"Dutch\", \"nn\": \"Norwegian Nynorsk\", \"no\": \"Norwegian\", \"nr\": \"South Ndebele\", \"nv\": \"Navajo\", \"ny\": \"Nyanja\",\n    \"oc\": \"Occitan\", \"oj\": \"Ojibwa\", \"om\": \"Oromo\", \"or\": \"Oriya\", \"os\": \"Ossetian\", \"pa\": \"Panjabi\", \"pl\": \"Polish\", \"ps\": \"Pushto\", \"pt\": \"Portuguese\", \"pt-PT\": \"Portuguese (Portugal)\", \"qu\": \"Quechua\",\n    \"rm\": \"Romansh\", \"rn\": \"Rundi\", \"ro\": \"Romanian\", \"ru\": \"Russian\", \"rw\": \"Kinyarwanda\",\n    \"sc\": \"Sardinian\", \"sd\": \"Sindhi\", \"se\": \"Northern Sami\", \"sg\": \"Sango\", \"si\": \"Sinhala\", \"sk\": \"Slovak\", \"sl\": \"Slovenian\", \"sm\": \"Samoan\", \"sn\": \"Shona\", \"so\": \"Somali\", \"sq\": \"Albanian\", \"sr\": \"Serbian\", \"ss\": \"Swati\", \"st\": \"Southern Sotho\", \"su\": \"Sundanese\", \"sv\": \"Swedish\", \"sw\": \"Swahili\",\n    \"ta\": \"Tamil\", \"te\": \"Telugu\", \"tg\": \"Tajik\", \"th\": \"Thai\", \"ti\": \"Tigrinya\", \"tk\": \"Turkmen\", \"tl\": \"Tagalog\", \"tn\": \"Tswana\", \"to\": \"Tonga\", \"tr\": \"Turkish\", \"ts\": \"Tsonga\", \"tt\": \"Tatar\", \"tw\": \"Twi\", \"ty\": \"Tahitian\",\n    \"ug\": \"Uighur\", \"uk\": \"Ukrainian\", \"ur\": \"Urdu\", \"uz\": \"Uzbek\", \"ve\": \"Venda\", \"vi\": \"Vietnamese\", \"wa\": \"Walloon\", \"wo\": \"Wolof\", \"xh\": \"Xhosa\", \"yi\": \"Yiddish\", \"yo\": \"Yoruba\", \"za\": \"Zhuang\",\n    \"zh\": \"Chinese\", \"zh-Hans\": \"Simplified Chinese\", \"zh-Hant\": \"Traditional Chinese\", \"zu\": \"Zulu\",\n    \"avk\": \"Kotava\", \"jbo\": \"Lojban\", \"kab\": \"Kabyle\", \"tlh\": \"Klingon\", \"tok\": \"Toki Pona\", \"zgh\": \"Standard Moroccan Tamazight\",\n    \"sgn\": \"Sign Languages\", \"ase\": \"American Sign Language\", \"asq\": \"Austrian Sign Language\", \"bfi\": \"British Sign Language\", \"bzs\": \"Brazilian Sign Language\", \"csl\": \"Chinese Sign Language\", \"cse\": \"Czech Sign Language\", \"dsl\": \"Danish Sign Language\", \"fsl\": \"French Sign Language\", \"gsg\": \"German Sign Language\", \"jsl\": \"Japanese Sign Language\", \"pks\": \"Pakistan Sign Language\", \"rsl\": \"Russian Sign Language\", \"sdl\": \"Saudi Arabian Sign Language\", \"sfb\": \"Langue des signes de Belgique Francophone\", \"sfs\": \"South African Sign Language\", \"ssp\": \"Spanish Sign Language\", \"swl\": \"Swedish Sign Language\", \"tsq\": \"Thai Sign Language\",\n}\n```\nThe tests assert only `\"en\"` gives \"English\" and `\"zh-Hans\"` gives \"Simplified Chinese\". The stock list keeps both, so pasting the real list will not break them.\n\n---\n\n## 3. Server whitelist DB\n\n### `whitelist_migrations.py`\n```python\ndef migrate_videos_language(conn: sqlite3.Connection) -> None:\n    \"\"\"Add the nullable `language` column (PeerTube language code) to a videos table that predates it.\n\n    Additive and idempotent: rows, `videos_fts` and its triggers are untouched, since none reference `language`.\n    \"\"\"\n    if not _table_exists(conn, \"videos\"):\n        return\n    if \"language\" in _columns(conn, \"videos\"):\n        return\n    conn.execute(\"ALTER TABLE videos ADD COLUMN language TEXT\")\n```\n\n`migrate_videos_schema` rebuild changes:\n- add `has_language = \"language\" in columns` and `language_expr = \"language\" if has_language else \"NULL\"`;\n- add `language TEXT,` after `category TEXT,` in `videos_new`;\n- add `language,` after `category,` in the INSERT list;\n- add `{language_expr},` after `category,` in the SELECT list.\n\nThe INSERT and SELECT lists stay positionally aligned.\n\n`migrate_whitelist_schema` then calls, in order:\n```python\n    migrate_instances_schema(conn, table_name)\n    migrate_channels_schema(conn)\n    migrate_videos_schema(conn)\n    migrate_videos_language(conn)\n```\n\n### `sync-whitelist.py`\nIn `ensure_content_schema`, add `language TEXT,` after `category TEXT,`. Nothing else: `VIDEO_COLUMNS` picks the column up from `schema.sql`.\n\n---\n\n## 4. Crawler\n\n### `schema.sql`\nAdd `  language TEXT,` after `  category TEXT,`. Do not add an index on it: the first `db.exec(schemaSql)` runs against old tables.\n\n### `db.ts`\n```ts\nfunction applyBaseSchema(db: Database.Database) {\n  db.exec(schemaSql);\n  migrateInstances(db);\n  migrateChannels(db);\n  migrateVideos(db);\n  migrateVideosLanguage(db);\n  db.exec(schemaSql);\n}\n\n/**\n * Add the videos.language column (PeerTube language code) to a crawl DB that predates it.\n */\nfunction migrateVideosLanguage(db: Database.Database) {\n  if (!tableExists(db, \"videos\")) return;\n  if (getColumns(db, \"videos\").includes(\"language\")) return;\n  db.exec(\"ALTER TABLE videos ADD COLUMN language TEXT\");\n}\n```\n\n`migrateVideos`:\n- add `const hasLanguage = columns.includes(\"language\");` and `const languageExpr = hasLanguage ? \"language\" : \"NULL\";`;\n- add `language TEXT,` after `category TEXT,` in `videos_new`;\n- add `language,` after `category,` in the INSERT list;\n- add `${languageExpr},` after `category,` in the SELECT list.\n\n`VideoUpsertRow` gains `language: string | null;` after `category`.\n\n`upsertStmt`:\n- the INSERT list gains `language,` after `category,`;\n- VALUES becomes 26 `?` followed by `NULL, NULL, 0`;\n- ON CONFLICT gains `language = excluded.language,` after `category = excluded.category,`.\n\n`upsertVideos` gains `row.language,` directly after `row.category,`.\n\nAlignment check: the column list, the `?` count and the `run()` arguments each gain exactly one entry, in the same slot.\n\nThis follows the plan and keeps `language` consistent with `category`: a re-crawl whose payload has `{id: null}` sets crawl.db's `language` to NULL. This is noted in the inventory and stays as is.\n\n### `videos-worker.ts`\n```ts\ninterface PeerTubeLanguage {\n  id?: string | null;\n  label?: string;\n}\n```\n`PeerTubeVideo` gains `language?: PeerTubeLanguage | string;` after `category`. `toVideoRow` gains `language: extractLanguage(video.language),` after `category:`.\n```ts\n/**\n * Handle extract language: the PeerTube language code (an object's id or a plain string), trimmed; null otherwise, including a null id.\n */\nfunction extractLanguage(value: PeerTubeVideo[\"language\"]): string | null {\n  const raw = value && typeof value === \"object\" ? value.id : value;\n  const code = typeof raw === \"string\" ? raw.trim() : \"\";\n  return code || null;\n}\n```\nThe trim makes this match the handler's `pick_text` exactly: numbers, `\"\"` and whitespace all give `null`.\n\n### Dist\nRun `cd engine/crawler && npm install && npm run build`, then commit `dist/db.js`, `dist/videos-worker.js` and any other file tsc rewrites (for example `host-filters.js`). Review the full dist diff.\n\n---\n\n## 5. Video page\n\n### `video-page.html` (between `video-meta-row` and `video-description`)\n```html\n            <div id=\"video-taxonomy\" class=\"video-taxonomy\" hidden>\n              <span id=\"video-category\" class=\"taxonomy-item\" hidden><span class=\"taxonomy-label\">Category</span><span id=\"video-category-value\" class=\"taxonomy-value\"></span></span>\n              <span id=\"video-language\" class=\"taxonomy-item\" hidden><span class=\"taxonomy-label\">Language</span><span id=\"video-language-value\" class=\"taxonomy-value\"></span></span>\n              <ul id=\"video-tags\" class=\"video-tags\" aria-label=\"Tags\"></ul>\n            </div>\n```\nThere are no inline styles, because of the CSP. Elements are hidden with the `hidden` attribute.\n\n### `index.ts`\nNew element lookups go with the others at the top:\n```ts\nconst taxonomyEl = document.getElementById(\"video-taxonomy\");\nconst categoryEl = document.getElementById(\"video-category\");\nconst categoryValueEl = document.getElementById(\"video-category-value\");\nconst languageEl = document.getElementById(\"video-language\");\nconst languageValueEl = document.getElementById(\"video-language-value\");\nconst tagsEl = document.getElementById(\"video-tags\");\n```\n\n`VideoMetadata` gains `tags?: string[]; category?: string; language?: string;`.\n\n`fetchVideoMetadataFromServer` return gains:\n```ts\n      tags: toStringList(data.tags),\n      category: typeof data.category === \"string\" ? data.category : \"\",\n      language: typeof data.language === \"string\" ? data.language : \"\",\n```\n\n`fetchVideoMetadataFromInstance` return gains:\n```ts\n      tags: toStringList(data.tags),\n      category: peerTubeLabel(data.category, false),\n      language: peerTubeLabel(data.language, true),\n```\n\nNew helpers, placed near `normalizeNumber`:\n```ts\n/**\n * Handle to string list: the string elements of an array, else [].\n */\nfunction toStringList(value: unknown): string[] {\n  return Array.isArray(value) ? value.filter((item): item is string => typeof item === \"string\") : [];\n}\n\n/**\n * Handle PeerTube label: the trimmed `label` of a `{id, label}` object; with requireId, \"\" when the id is null (PeerTube's unset value).\n */\nfunction peerTubeLabel(value: unknown, requireId: boolean): string {\n  if (!value || typeof value !== \"object\") return \"\";\n  const { id, label } = value as { id?: unknown; label?: unknown };\n  if (requireId && (id === null || id === undefined)) return \"\";\n  return typeof label === \"string\" ? label.trim() : \"\";\n}\n\n/**\n * Handle render taxonomy: category, language and tag chips via textContent only; the whole block is hidden when no metadata resolved.\n */\nfunction renderTaxonomy(metadata: VideoMetadata | null) {\n  if (!taxonomyEl) return;\n  taxonomyEl.hidden = !metadata;\n  if (!metadata) return;\n  setTaxonomyItem(categoryEl, categoryValueEl, metadata.category ?? \"\");\n  setTaxonomyItem(languageEl, languageValueEl, metadata.language ?? \"\");\n  if (tagsEl) {\n    const tags = metadata.tags ?? [];\n    const items = tags.map((tag) => {\n      const item = document.createElement(\"li\");\n      item.className = \"tag-chip\";\n      item.textContent = tag;\n      return item;\n    });\n    if (items.length === 0) {\n      const empty = document.createElement(\"li\");\n      empty.className = \"video-tags-empty\";\n      empty.textContent = \"No tags\";\n      items.push(empty);\n    }\n    tagsEl.replaceChildren(...items);\n  }\n}\n\n/**\n * Handle set taxonomy item: show the value, or hide the item when it is empty.\n */\nfunction setTaxonomyItem(itemEl: HTMLElement | null, valueEl: HTMLElement | null, value: string) {\n  if (valueEl) valueEl.textContent = value;\n  if (itemEl) itemEl.hidden = !value;\n}\n```\n`loadVideo` calls `renderTaxonomy(metadata);` directly before the `descriptionEl` block.\n\nDecisions:\n- **No metadata at all.** When both fetches fail, the block is hidden: nothing is known, so \"No tags\" would be a claim the page cannot make.\n- **Language.** The instance fallback hides a null-id language, which matches the server path.\n- **Category.** \"Unknown\" shows on both paths, following R2 literally.\n\n### `video.css` (after `.metric svg`)\n```css\n.video-taxonomy {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.5rem 0.8rem;\n  font-size: 0.85rem;\n  color: var(--muted);\n}\n\n.video-taxonomy[hidden],\n.video-taxonomy [hidden] {\n  display: none;\n}\n\n.taxonomy-item {\n  display: inline-flex;\n  align-items: baseline;\n  gap: 0.35rem;\n}\n\n.taxonomy-label {\n  font-size: 0.8rem;\n  text-transform: uppercase;\n  letter-spacing: 0.04em;\n}\n\n.taxonomy-value {\n  color: var(--accent-strong);\n  font-weight: 600;\n}\n\n.video-tags {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.35rem;\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n\n.tag-chip {\n  padding: 0.15rem 0.55rem;\n  border-radius: 999px;\n  background: rgba(180, 87, 55, 0.08);\n  color: var(--accent-strong);\n  font-size: 0.8rem;\n}\n\n.video-tags-empty {\n  font-style: italic;\n}\n```\nThe explicit `[hidden]` rule is needed because an author `display:` rule overrides the UA default.\n\n### `client/frontend/dist`\nRun `npm run build`, commit the new hashed `video-*.js` / `video-*.css` and `dist/video-page.html`, and delete the orphaned `video-gjYm1MC8.js` and `video-ypOuFwNw.css`, plus any re-hashed shared chunk.\n\n---\n\n## 6. Tests\n\n### `tests/active/test_video_handler.py` (new)\nModule docstring, in the suite's bullet style:\n```text\n\"\"\"`/api/video` (`handle_video_request`) refreshes the stored video from its source instance only when the video detail fetch returns a JSON object, answers from one merged value set, and maps category and language to PeerTube default labels; `migrate_whitelist_schema` adds `videos.language` to an existing whitelist DB.\n\n- A successful fetch writes the source title, description, stats, tags_json, category, language, nsfw, duration and thumbnail_url, moves last_checked_at forward, clears instances.last_error/_at/_source, and the response carries tags, category, language, nsfw, duration and thumbnailUrl.\n- A caught network error (the fetch stub returning None, and the real fetch with urlopen raising URLError) and a malformed body (not JSON, bad UTF-8, a JSON list) leave every videos and channels column and instances.last_error as they were, and the response equals the DB values.\n- A payload with stats but no tags or category keeps the stored tags_json and category; `tags: []` stores \"[]\" and answers `tags: []`.\n- A source change between two requests is reflected in the second response and in the DB.\n- A stored \"15\" answers \"Science & Technology\", \"99\" answers \"99\", \"Music\" answers \"Music\", \"en\" answers \"English\", \"zh-Hans\" answers \"Simplified Chinese\", \"xx\" answers \"xx\".\n- The migration adds `language` to a pre-change videos table, keeps every row and the three FTS triggers, and a second run changes nothing.\n\nThe DB schema, triggers included, comes from `sync-whitelist.py`; the instance is never contacted: `fetch_instance_json` or `urlopen` is replaced on `handlers.video`.\n\"\"\"\n```\n\nSetup, following `test_internal_events.py` and `test_repair_video_channel_names.py`:\n```python\nROOT = Path(__file__).resolve().parents[2]\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nAPI_DIR = SERVER_DIR / \"api\"\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nfor path in (SERVER_DIR, API_DIR):\n    if str(path) not in sys.path:\n        sys.path.insert(0, str(path))\n\nfrom handlers import video  # noqa: E402\n\nHOST = \"peer.example\"\nOLD_CHECKED_AT = 1_000\nVIDEO_PATH = \"/api/v1/videos/v1\"\nCHANNEL_PATH = \"/api/v1/video-channels/newslug\"\nPARAMS = {\"id\": [\"v1\"], \"host\": [HOST]}\nSOURCE = {\"name\": \"New title\", \"description\": \"New desc\", \"views\": 50, \"likes\": 5, \"dislikes\": 1, \"tags\": [\"alpha\", \"beta\"], \"category\": {\"id\": 15, \"label\": \"Science & Technology\"}, \"language\": {\"id\": \"en\", \"label\": \"English\"}, \"nsfw\": True, \"duration\": 321, \"thumbnailPath\": \"/static/thumbnails/new.jpg\", \"channel\": {\"name\": \"newslug\", \"displayName\": \"New Chan\"}}\n```\n\n**Fixtures:**\n- `_load_job(name, filename)`, copied from the repair test.\n- `sync_job` and `migrations`, module scope, loaded as `sync_whitelist_video_handler` and `whitelist_migrations_video_handler`.\n- `server(tmp_path, sync_job)`:\n  - opens `sqlite3.connect(tmp_path / \"whitelist.db\", check_same_thread=False)` and sets `row_factory = sqlite3.Row`;\n  - runs `ensure_whitelist_schema` and `ensure_content_schema`;\n  - seeds one `instances` row (`HOST`, `last_error='boom'`, `last_error_at=5`, `last_error_source='video'`);\n  - seeds one `channels` row (`'7', HOST, channel_name 'oldslug', display_name 'Old Chan', followers_count 3`);\n  - seeds one `videos` row with every column below:\n\n| Column | Value |\n|---|---|\n| `video_id` | `'v1'` |\n| `video_uuid` | `'uuid-1'` |\n| `instance_domain` | `HOST` |\n| `channel_id` | `'7'` |\n| `channel_name` | `'Old Chan'` |\n| `title` | `'Old title'` |\n| `description` | `'Old desc'` |\n| `tags_json` | `'[\"old\"]'` |\n| `category` | `'Music'` |\n| `language` | `'fr'` |\n| `nsfw` | `0` |\n| `duration` | `10` |\n| `thumbnail_url` | `'https://peer.example/old.jpg'` |\n| `views` | `1` |\n| `likes` | `1` |\n| `dislikes` | `0` |\n| `published_at` | `1_600_000_000_000` |\n| `last_checked_at` | `OLD_CHECKED_AT` |\n\n  - commits, and returns `SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)`;\n  - closes the connection on teardown.\n- `responses(monkeypatch)`: patches `video.respond_json` to append `(status, body)` and returns the list.\n- `_serve(monkeypatch, payloads: dict[str, dict | None])`: patches `video.fetch_instance_json` with `lambda host, path: payloads.get(path)`.\n- `_snapshot(conn)`: returns `SELECT * FROM videos WHERE video_id='v1'`, `SELECT * FROM channels`, and `SELECT last_error, last_error_at, last_error_source FROM instances`, each as a tuple of `tuple(row)`.\n- `_FakeResponse(body: bytes)`: `status = 200`, `__enter__` returns self, `__exit__` returns False, and `read()` returns the body.\n\n**Tests:**\n- `test_success_refreshes_row_and_response`. It serves `{VIDEO_PATH: SOURCE, CHANNEL_PATH: {\"followersCount\": 9}}`, calls `video.handle_video_request(None, server, PARAMS)`, and asserts:\n  - the DB row's title, description, views, likes, dislikes, tags_json, category, language, nsfw, duration and thumbnail_url equal `(\"New title\", \"New desc\", 50, 5, 1, '[\"alpha\", \"beta\"]', \"Science & Technology\", \"en\", 1, 321, \"https://peer.example/static/thumbnails/new.jpg\")`;\n  - `last_checked_at > OLD_CHECKED_AT`;\n  - `instances.last_error*` are all NULL;\n  - the response is status 200 with `tags == [\"alpha\", \"beta\"]`, `category == \"Science & Technology\"`, `language == \"English\"`, `nsfw is True`, `duration == 321` and `thumbnailUrl` equal to the stored URL;\n  - the 18 original keys are all still present.\n- `test_fetch_failure_leaves_db_untouched`, parametrised with ids:\n  - `stub-none`: `_serve` with `{}`;\n  - `urlopen-urlerror`: `monkeypatch.setattr(video, \"urlopen\", raising URLError(\"down\"))`;\n  - `not-json`: `urlopen` returns `_FakeResponse(b\"<html>\")`;\n  - `bad-utf8`: body `b\"\\xff\\xfe\"`;\n  - `json-list`: body `b\"[1, 2]\"`.\n\n  It asserts `_snapshot` is equal before and after (every column, `last_checked_at` included, `last_error == 'boom'`) and that the response is status 200 with `title == \"Old title\"`, `description == \"Old desc\"`, `views == 1`, `tags == [\"old\"]`, `category == \"Music\"`, `language == \"French\"`, `nsfw is False`, `duration == 10`, `thumbnailUrl == \"https://peer.example/old.jpg\"` and `channelName == \"Old Chan\"`.\n- `test_partial_payload_keeps_tags_and_category`. It serves `{VIDEO_PATH: {\"views\": 77}}` and asserts the DB has `views == 77`, `tags_json == '[\"old\"]'`, `category == \"Music\"` and `language == \"fr\"`, and the response has `tags == [\"old\"]` and `category == \"Music\"`.\n- `test_empty_tag_list_propagates`. It serves `{VIDEO_PATH: {\"tags\": []}}` and asserts the DB has `tags_json == \"[]\"` and the response has `tags == []`.\n- `test_second_request_reflects_source_change`. The first request uses `SOURCE`. The second uses `{**SOURCE, \"name\": \"Renamed\", \"tags\": [\"gamma\"]}`, with the same `payloads` dict mutated. It asserts the second response has title \"Renamed\" and tags `[\"gamma\"]`, and the DB has the same values.\n- `test_response_labels`, parametrised on `(category, language, expected_category, expected_language)`:\n  - `(\"15\", \"en\", \"Science & Technology\", \"English\")`;\n  - `(\"99\", \"zh-Hans\", \"99\", \"Simplified Chinese\")`;\n  - `(\"Music\", \"xx\", \"Music\", \"xx\")`.\n\n  It UPDATEs the seeded row, serves `{}` (so the answer comes from the DB), and asserts the response labels.\n- `test_migration_adds_language_column(tmp_path, sync_job, migrations)`:\n  - creates the pre-change `videos` table inline. Its DDL is the whitelist `videos` DDL without `language`, error columns included, so only the additive path runs;\n  - then runs `ensure_whitelist_schema` + `ensure_content_schema` (FTS and triggers are created, and `videos` is left as is), and inserts two videos;\n  - runs `migrations.migrate_whitelist_schema(conn, \"instances\")` and asserts:\n    - `\"language\"` is in the `PRAGMA table_info(videos)` names;\n    - the `SELECT video_id, title, tags_json, category FROM videos ORDER BY video_id` rows are unchanged, and `language` is NULL for both;\n    - `SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'videos_fts_%'` equals 3;\n    - a second run leaves the `PRAGMA table_info(videos)` output identical.\n\n### `tests/active/test_videos_worker.py`\n- Extract the body of the existing test into `_crawl(tmp_path, schema_sql: str, alpha_videos: list[dict]) -> tuple[Path, str, str, str, str, CompletedProcess]`. It holds the node, dist and git asserts, the two stand-ins, the seeding through `conn.executescript(schema_sql)` and the node run.\n- Existing test: alpha videos gain `\"language\": {\"id\": \"en\", \"label\": \"English\"}` (a-1) and `\"language\": {\"id\": None, \"label\": \"Unknown\"}` (a-2). It additionally asserts `SELECT video_id, language FROM videos` gives `{\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}`.\n- New `test_crawl_adds_language_to_existing_db`:\n  - `legacy = SCHEMA.read_text(encoding=\"utf-8\").replace(\"  language TEXT,\\n\", \"\")`, and it asserts `legacy != SCHEMA.read_text(...)` so the fixture really lacks the column;\n  - runs `_crawl` with alpha `[{\"uuid\": \"a-1\", \"name\": \"A one\", \"language\": \"de\"}]`;\n  - asserts `\"language\" in PRAGMA table_info(videos)` names and that a-1's `language == \"de\"`.\n- The docstring gains two bullets:\n  - \"Each video's `language` is the PeerTube language id, NULL for a null id or no language.\"\n  - \"A crawl.db created before `language` existed gains the column when the crawler opens it, and the crawl fills it.\"\n\n### Harvest-time (not in this worktree's code)\n- In `.un/skills/devsecops/config.json` `test_groups`, map the new test to `video.py`, `peertube_labels.py`, `whitelist_migrations.py` and `sync-whitelist.py`.\n- Extend `test_videos_worker.py`'s group with `src/db.ts`, `dist/db.js` and `schema.sql`.\n- The documentation checklist is settled and carried separately.\n\n---\n\n## Check against plan and requirements (ladder rung 2)\n\n### Pass 1\n**R1**\n- `fetch_instance_video_dynamic` returning `None` is the only success signal, and the guard is `dynamic is not None`.\n- Parse and non-dict failures return `None`; the kept exceptions and the non-200 case are unchanged.\n- A channel-detail failure still falls back.\n- A failure runs no statement at all.\n\n**R2**\n- Every field uses a present-and-valid-or-DB rule, and `thumbnail_url` maps `\"\"` to `None`.\n- `\"[]\"` propagates.\n- `extract_category` handles an id-only category, and a blank string keeps the DB value.\n- `language` holds the code, and a null id keeps the DB value.\n- There is one UPDATE path.\n\n**R3**\n- `schema.sql`, the `db.ts` ALTER, the rebuild and the upsert, `videos-worker.ts`, sync, the whitelist migration and its rebuild, `fetch_video_row` and the dist rebuild are all covered.\n\n**R4**\n- There is a stdlib map. The category lookup is digit-only, and unknown values stay raw.\n- The simplification is named in the module docstring.\n\n**R5**\n- There are six new keys with the specified types, and the 18 old keys are kept.\n- The proxy is untouched.\n\n**R6**\n- There is a block with hidden-when-empty category and language and a \"No tags\" state.\n- Both fetch paths fill it, and everything is set through `textContent` / `createElement`.\n- The CSS is compact and there are no inline styles.\n- The dist is rebuilt.\n\n**R7**\n- Every listed fixture maps to a test in the table at the top.\n- The failure assertions use full-row `SELECT *` snapshots.\n- The DB comes from the production schema helpers, and nothing touches the network.\n\n### Pass 1 findings, fixed in place\n- **Language rule divergence.** TS `toNullableString` does not trim, while Python `pick_text` does, so the two producers could store different values. `extractLanguage` now trims.\n- **Destructive migration path.** The legacy table in the migration test would otherwise have gone down the destructive rebuild path. It is now built with the error columns present.\n\n### Pass 2\nNothing unmet.\n\nThe simplifications, all named:\n- default-only labels (R4);\n- a whitespace-only language id is treated as absent on both producers;\n- the draft `LANGUAGE_LABELS` literal is marked for wholesale replacement from a stock instance before commit.\n",
  "coordination": "Phase 1 needs `cd engine/crawler && npm install && npm run build` so the committed dist is current; otherwise `test_videos_worker.py` fails on a stale dist. Phase 2 needs a manual step: `LANGUAGE_LABELS` must be replaced wholesale with the JSON from a stock PeerTube instance's `GET /api/v1/videos/languages` (a live endpoint), as the settled draft requires; the checkpoint only asserts \"en\", \"zh-Hans\" and unknown codes, so it cannot catch a bad transcription. Phase 4 needs `client/frontend/node_modules` (esbuild) installed and `npm run build` for the committed dist. Deployment (after the merge, not a checkpoint): run the crawler once and `migrate-whitelist.py` on every whitelist.db before restarting the Engine.",
  "tests": {
    "tests/tmp/test_10_video_metadata_completeness_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase1.py:115, :116, :117, :119, :120, :122, :128, :129, :130, :131. Checked after `migrate_whitelist_schema(conn, \"instances\")` runs on a pre-change whitelist videos table (the column's absence is confirmed at :109 and the triggers are confirmed at :110). There is exactly one `language` column (:115) and it is nullable (:116). The rows read back as literal seeds with language NULL (:117). The three `videos_fts_*` triggers are present (:119). MATCH still finds v1 (:120), and a row v3 inserted afterwards is also found (:122). A second run leaves table_info (:128), the rows (:129), the triggers (:130) and both MATCH results (:131) unchanged.",
          "expected": "`language` table_info notnull 0. Rows [(\"v1\",\"Alpine walk\",'[\"hike\"]',\"Travels\",None), (\"v2\",\"Harbour night\",None,None,None)]. Triggers [ad, ai, au]. {\"v1\"} for \"Alpine\" and {\"v3\"} for \"Lantern\", before and after the second run. Second-run table_info and rows equal the first-run snapshots.",
          "wrong_implementation": "Today's migration adds nothing, so :115 finds 0 columns. A rebuild through `migrate_videos_schema` drops the triggers, so :119 reads []. A rebuild that never repopulates the index gives :120/:131 an empty set. An unconditional ALTER on the second run raises \"duplicate column name: language\". A second run that resets rows loses v3's 'fr', which fails :129."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase1.py:225, :257, :261. At :225, the built dist under node crawls two stand-ins and crawl.db holds {a-1: \"en\", a-2: None, b-1: None}. At :257 and :261, a crawl.db seeded from schema.sql with its language line stripped (absence confirmed at :247) gains the column (:257). The rows then read [(\"a-0\",\"Old one\",None), (\"a-1\",\"A one\",\"de\")] (:261).",
          "expected": "{\"a-1\": \"en\", \"a-2\": None, \"b-1\": None}. `language` is in the column names. [(\"a-0\",\"Old one\",None), (\"a-1\",\"A one\",\"de\")].",
          "wrong_implementation": "Storing the label gives \"English\"/\"Unknown\". Ignoring the field gives all None. A db.ts with no ALTER migration leaves the existing crawl.db without the column, so :257 fails. Adding language to the INSERT but not to `ON CONFLICT DO UPDATE SET` leaves a-1 NULL at :261. A column add that rebuilds the table without copying rows loses a-0."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing."
        },
        {
          "id": "C2",
          "text": "A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_video_metadata_completeness_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_10_video_metadata_completeness_phase1.py  3 failed                               0.0s\n  -------------------------------------------------------\n  total                                                    3 failed                               1.8s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_10_video_metadata_completeness_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase2.py:82 \u2014 `body.get(\"category\", \"MISSING\") == expected_category` over five DB-only cases (fetch stubbed to None): \"15\"\u2192\"Science & Technology\", \"18\"\u2192\"Food\", \"99\"\u2192\"99\", \"19\"\u2192\"19\", \"Music\"\u2192\"Music\"; backed on a success refresh by :104 (`category == \"Science & Technology\"` for a stored \"15\") and :103 (stored category is still \"15\")",
          "expected": "\"Science & Technology\", \"Food\", \"99\", \"19\", \"Music\" for the five cases, and \"Science & Technology\" at :104. The current code sends no `category` key at all; the run showed 'MISSING' at :82 in all five cases and at :104.",
          "wrong_implementation": "No mapping, just adding `\"category\": category` to the response: \"15\" and \"18\" answer raw \"15\"/\"18\", red. A map missing an entry or shifted by one (e.g. only ids 1\u201317): \"18\" answers \"18\" instead of \"Food\", red. A lookup that returns \"\" or None for an unknown id, or one that tries int() on any value: \"99\", \"19\" or \"Music\" answers \"\"/None or raises, red. A handler that turns the stored value into the label before the UPDATE and writes it back: :103 reads \"Science & Technology\" instead of \"15\", red."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase2.py:83 \u2014 `body.get(\"language\", \"MISSING\") == expected_language` over \"en\"\u2192\"English\", \"zh-Hans\"\u2192\"Simplified Chinese\", \"xx\"\u2192\"xx\"; backed by :105 (`language == \"English\"` on a success refresh with stored \"en\") and :103 (stored language is still \"en\")",
          "expected": "\"English\", \"Simplified Chinese\", \"xx\", and \"English\" at :105. The current code sends no `language` key: the probe's captured body had no `language` at all, so today :83 and :105 read 'MISSING'. The run never reached them because the category check fails first.",
          "wrong_implementation": "Sending the raw code (`\"language\": row[\"language\"]`): \"en\" answers \"en\", red. A lookup that lowercases or strips the region part: \"zh-Hans\" becomes \"zh-hans\" or \"zh\" and answers raw or \"Chinese\" instead of \"Simplified Chinese\", red. An unknown code mapped to \"\" or \"Unknown\": \"xx\" answers that, red. Not selecting `v.language` in `fetch_video_row`: every case answers \"\"/MISSING, red. Writing the label back into the row: :103 reads \"English\", red."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored."
        },
        {
          "id": "C2",
          "text": "A stored language code is answered with its PeerTube default label, and an unknown code is answered raw."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_video_metadata_completeness_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_10_video_metadata_completeness_phase2.py  6 failed                               0.0s\n  -------------------------------------------------------\n  total                                                    6 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_10_video_metadata_completeness_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase3.py:150 \u2014 the full videos row, every channels row and instances.last_error* all equal the pre-request snapshot, for URLError, 404, not-json, bad-utf8 and json-list. :151 \u2014 the response answers STORED_ANSWER: title, description, views 1, likes 1, dislikes 0, tags [\"old\"], category \"Music\", language \"French\", duration 10, the old thumbnail, channelName \"Old Chan\", subscribersCount 3. :152 \u2014 nsfw is False.",
          "expected": "Snapshot unchanged, including (\"boom\", 5, \"video\"). The response carries the seeded DB values, and nsfw is the bool False.",
          "wrong_implementation": "Today's code writes on URLError and 404: last_checked_at goes 1000 \u2192 now, popularity moves, and the instance error is cleared. The three bad bodies raise. A failure path that answers None or a default for likes, dislikes or subscribersCount, or leaves out tags, duration or thumbnailUrl (\"MISSING\"), fails :151."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase3.py:164/:166/:168/:169/:170/:171/:173/:174 \u2014 full SOURCE: row, channels, cleared error, original keys and merged response. :196/:197/:199/:200 \u2014 absent and null-or-blank payloads: the row keeps the seed except views 77, channels rows are unchanged, and the response is STORED_ANSWER with views 77 (likes 1, dislikes 0, subscribersCount 3 included) and nsfw False. :211/:212 \u2014 failed channel-detail fetch: channels (\"newslug\", \"New Chan\", 3), and the response channelName \"New Chan\" with subscribersCount 3. :221/:222 \u2014 tags [] stores \"[]\" and answers []. :234\u2013:236 \u2014 an object body, {} included, is a success. :248/:250 \u2014 the second request reflects the source change.",
          "expected": "Source values where present, DB values where absent, in the videos row, the channels row and the response alike.",
          "wrong_implementation": "Today's code leaves language \"fr\", duration 10 and the old thumbnail in the row after a full payload (fails :168). It answers no tags, duration or thumbnailUrl (fails :199 as \"MISSING\", observed). A merge that writes NULL followers after a failed channel fetch fails :211. One that nulls the channel slug or display name on an absent channel fails :197. A response that disagrees with the row on likes, dislikes or subscribersCount fails :199."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values."
        },
        {
          "id": "C2",
          "text": "A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_video_metadata_completeness_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_10_video_metadata_completeness_phase3.py  12 failed, 1 passed                    0.0s\n  -------------------------------------------------------\n  total                                                    12 failed, 1 passed                    0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_10_video_metadata_completeness_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase4.py:116, :118, :134 assert that `video-category` and `video-language` are `hidden is False` after load. Both items start hidden (`initially_hidden=ITEMS`, and `[\"video-category\"]` in case 3). Lines :117, :119 and :135 assert that the `video-category-value` and `video-language-value` text is \"Science & Technology\", \"English\" and \"Music\". Line :120 asserts that the `video-tags` children equal `[{\"text\": \"alpha\", \"chip\": True}, {\"text\": \"beta\", \"chip\": True}]`, and :137 that they equal `[{\"text\": \"solo\", \"chip\": True}]`.",
          "expected": "This is what the probe's RIGHT renderer produced when run through this exact RUNNER and `_page`, not a prediction. The RIGHT renderer sets `hidden = !value`, sets `textContent` on the value element, and calls `replaceChildren` with `createElement` + `className = \"tag-chip\"` + `textContent` chips, which is the plan's `setTaxonomyItem`/`renderTaxonomy` shape. Case 1 reported video-category {hidden: False}, video-category-value {text: 'Science & Technology'}, video-language {hidden: False}, video-language-value {text: 'English'}, and tags [{'text': 'alpha', 'chip': True}, {'text': 'beta', 'chip': True}]. Case 3 reported video-category {hidden: False}, value 'Music', and tags [{'text': 'solo', 'chip': True}]. On today's page each of these ids reads {text: None, hidden: None} and tags reads [].",
          "wrong_implementation": "Wrong implementation 1: the chips are built with `innerHTML = tags.map(t => `<span class=\"tag-chip\">${t}</span>`).join(\"\")`, markup instead of text chips. The probe's WRONG run shows tags [{'text': '', 'chip': False}], so :120 and :137 go red. Wrong implementation 2: a renderer that never clears the item's `hidden`, such as the HTML's `hidden` attribute left in place. The item then stays at its starting hidden=True, so :116, :118 and :134 go red. Wrong implementation 3: a renderer that writes the value into the item instead of `*-value`. The value element then reads None or '', so :117, :119 and :135 go red. Wrong implementation 4: an off-by-one or a renderer that drops tags. The list comparison at :137 (length 1) and :120 (length 2, in order) catches both."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_10_video_metadata_completeness_phase4.py:126 and :127 assert that `video-category` and `video-language` are `hidden is True` for a body with `category: \"\"` and `language: \"\"`. Both items start visible (`initially_hidden=[]`). Line :128 asserts that the texts of the `video-tags` children equal `[\"No tags\"]`. Line :136 asserts that `video-language` is `hidden is True` in case 3, where the category is non-empty and starts hidden.",
          "expected": "This is observed from the probe's RIGHT renderer through this RUNNER. Case 2 reported video-category {hidden: True}, video-language {hidden: True}, and tags [{'text': 'No tags', 'chip': False}], so the child texts are ['No tags']. Case 3 reported video-language {hidden: True} while video-category was {hidden: False}. On today's page the ids read hidden None and tags reads [].",
          "wrong_implementation": "Wrong implementation 1: category is always shown, e.g. `removeAttribute(\"hidden\")` whatever the value. The probe's WRONG run showed case 2 video-category {hidden: False}, so :126 goes red. Wrong implementation 2: the language item's visibility is keyed on the category's emptiness, a copy-paste slip. WRONG case 3 showed video-language {hidden: False}, so :136 goes red. Case 2 alone cannot tell this apart, because both fields are empty there. Wrong implementation 3: \"No tags\" is written through `innerHTML` as markup. WRONG case 2 showed tags [{'text': '', 'chip': False}], so :128 goes red. Wrong implementation 4: an empty tag list renders nothing. The child texts are then [], so :128 goes red. Because the items start visible, a renderer that never touches `hidden` also fails :126 and :127."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag."
        },
        {
          "id": "C2",
          "text": "For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads \"No tags\"."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_10_video_metadata_completeness_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_10_video_metadata_completeness_phase4.py  3 failed                               0.0s\n  -------------------------------------------------------\n  total                                                    3 failed                               0.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_10_video_metadata_completeness_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_migration_adds_language_column` fails at line 115 on `assert len(language) == 1` because the `language` list is empty: `migrate_whitelist_schema` \u2192 `migrate_videos_schema` does not add the column yet. `test_crawl_stores_each_videos_language` fails at line 220 on `assert \"language\" in _column_names(conn)`, because neither `schema.sql` nor `dist/db.js` creates or adds `videos.language` yet. `test_crawl_adds_language_to_existing_db` fails at line 256 on the same membership check. In the second and third tests, the staleness assertion at line 158 fires first if the dist is found older than its source.\n\nNOT ASSESSED\n1. `src/videos-worker.ts`, `src/db.ts`, `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` were not read in full. I answered the stub question from the assertion form and from grepping the dist and `schema.sql`, which contain no `language` column yet.\n2. No `fixtures_path` was supplied. None is needed: the test uses only pytest's built-in `tmp_path` and builds everything else inline.\n3. Whether node and git are installed, and whether the dists are older than their sources, can only be settled by running the test. So line 158 may fail before lines 220/256 in the second and third tests.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |\n| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or one that mis-maps the seeded title/tags_json/category values | CARRIED |\n| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and does not recreate them (`migrate_videos_schema` drops them on rebuild) | CARRIED |\n| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that alters columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |\n| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :224 | not storing the code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` next to a-2/b-1 NULL) | CARRIED |\n| C2b | must_prove | NULL for a null id | :224 (`\"a-2\": None`) | storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code | CARRIED |\n| C2c | must_prove | including in a crawl.db created before the column existed | :256, :260 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |\n| D1a | docstring | \"every videos table this build touches gains a nullable `language` column\" | :116, :224, :260 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :224/:260) | CARRIED |\n| D1b | docstring | \"...holding the PeerTube language code\", which includes the whitelist `videos` table | none | whitelist `language` only ever gets a hand-inserted `'fr'` at :121. Nothing shows a sync carrying a crawl.db code into it | UNCARRIED |\n| D2 | docstring | \"adds a nullable `language` column\" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |\n| D3 | docstring | \"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |\n| D4 | docstring | \"the three `videos_fts_*` triggers still exist\" | :119 | triggers lost in a rebuild | CARRIED |\n| D5 | docstring | \"a title MATCH still finds the preserved row\" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |\n| D6 | docstring | \"and a row inserted afterwards\" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |\n| D7 | docstring | \"a second run leaves `table_info`, the rows and the triggers identical\" | :128, :129, :130 | a non-idempotent second run | CARRIED |\n| D8a | docstring | \"`dist/videos-worker.js`, run under node against local PeerTube stand-ins\" | :188, :216, :224 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |\n| D8b | docstring | \"the committed `dist/videos-worker.js`\" | none | the dirty branch at :146-147 accepts an uncommitted dist on mtime alone, so nothing requires the dist to be committed | UNCARRIED |\n| D9 | docstring | \"`\"en\"` for a video carrying it\" | :224 | storing the label, or nothing | CARRIED |\n| D10 | docstring | \"NULL for `{\"id\": null}`\" | :224 | storing `\"Unknown\"` or the string `\"null\"` | CARRIED |\n| D11 | docstring | \"NULL for a video with no `language`\" | :224 (`\"b-1\": None`) | a crash or a stale value when the field is absent | CARRIED |\n| D12 | docstring | crawl.db seeded from `schema.sql` with the `language` line removed, \"so the table really lacks the column\" | :232, :246 | a seed that still has the column, which would make C2c vacuous | CARRIED |\n| D13 | docstring | \"the crawl adds the column\" | :256 | no migration of an existing crawl.db | CARRIED |\n| D14 | docstring | \"keeps the video it did not revisit with `language` NULL\" | :260 (`(\"a-0\", \"Old one\", None)`) | a column add that rebuilds the table and drops rows | CARRIED |\n| D15 | docstring | \"stores `\"de\"` on the one it did\" | :260 (`(\"a-1\", \"A one\", \"de\")`) | an upsert whose `ON CONFLICT` set omits `language` | CARRIED |\n| D16 | docstring | \"a missing node or git ... fails the test rather than skipping it\" | :153, :155 | a `pytest.skip` when a tool is missing | CARRIED |\n| D17 | docstring | \"a missing or stale dist ... fails the test\" | :157, :158 | running a missing or out-of-date build without complaint | CARRIED |\n| D18 | docstring | \"a nonzero node exit fails the test\" | :216, :252 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |\n| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |\n| N2 | name | `test_crawl_stores_each_videos_language` | :224 | a per-video value that is missing or shared | CARRIED |\n| N3 | name | `test_crawl_adds_language_to_existing_db` | :256, :260 | an existing crawl.db that is left without the column | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:1\n   D1b is UNCARRIED. The opening sentence says every videos table touched holds \"the PeerTube language code\". For the whitelist table the only value it ever holds is a hand-written `'fr'` (:121). No assertion shows a code crawled into crawl.db reaching whitelist `videos.language`, which is the job of `rebuild_content_tables` in sync-whitelist.py (listed as EDITED). Either assert that path or narrow the sentence. It is not in `must_prove`, so it does not block.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:4\n   D8b is UNCARRIED. The docstring says \"the committed `dist/videos-worker.js`\", but `_dist_is_stale` (:146-147) falls back to mtime when either file is dirty or uncommitted. An uncommitted dist therefore passes. Either require a committed, clean dist or drop \"committed\" from the sentence.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:127-130\n   Leftover gap in C1d (still CARRIED). After the second run the test checks table_info, five columns of each row, and the trigger names, but not the index. A second run that rebuilds `videos`, recreates the triggers and leaves `videos_fts` empty would pass. Re-running `_matches` after :127 would close this.\n4. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:199\n   `language` is tested present-with-id, `{\"id\": null}` and absent. Malformed shapes are not tested: `language` as a bare string, `language: null`, or a non-string `id`.\n5. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:99\n   `test_migration_adds_language_column` says what happens but not when: on a pre-change whitelist DB, keeping rows and triggers, idempotently. If the test fails on :128-130 (the second run), the runner output still names only \"adds language column\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js, tests/active/test_video_handler.py and tests/active/test_videos_worker.py. I did not read them. The crawl path was judged from engine/crawler/src/db.ts and src/videos-worker.ts, which the test requires the dist to be no older than (:156-158).\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines everything else itself, so I looked for no conftest.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_migration_adds_language_column` fails at line 115 on `assert len(language) == 1` because the `language` list is empty: `migrate_whitelist_schema` \u2192 `migrate_videos_schema` does not add the column yet. `test_crawl_stores_each_videos_language` fails at line 220 on `assert \"language\" in _column_names(conn)`, because neither `schema.sql` nor `dist/db.js` creates or adds `videos.language` yet. `test_crawl_adds_language_to_existing_db` fails at line 256 on the same membership check. In the second and third tests, the staleness assertion at line 158 fires first if the dist is found older than its source.\n\nNOT ASSESSED\n1. `src/videos-worker.ts`, `src/db.ts`, `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` were not read in full. I answered the stub question from the assertion form and from grepping the dist and `schema.sql`, which contain no `language` column yet.\n2. No `fixtures_path` was supplied. None is needed: the test uses only pytest's built-in `tmp_path` and builds everything else inline.\n3. Whether node and git are installed, and whether the dists are older than their sources, can only be settled by running the test. So line 158 may fail before lines 220/256 in the second and third tests.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |\n| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or one that mis-maps the seeded title/tags_json/category values | CARRIED |\n| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and does not recreate them (`migrate_videos_schema` drops them on rebuild) | CARRIED |\n| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that alters columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |\n| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :224 | not storing the code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` next to a-2/b-1 NULL) | CARRIED |\n| C2b | must_prove | NULL for a null id | :224 (`\"a-2\": None`) | storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code | CARRIED |\n| C2c | must_prove | including in a crawl.db created before the column existed | :256, :260 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |\n| D1a | docstring | \"every videos table this build touches gains a nullable `language` column\" | :116, :224, :260 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :224/:260) | CARRIED |\n| D1b | docstring | \"...holding the PeerTube language code\", which includes the whitelist `videos` table | none | whitelist `language` only ever gets a hand-inserted `'fr'` at :121. Nothing shows a sync carrying a crawl.db code into it | UNCARRIED |\n| D2 | docstring | \"adds a nullable `language` column\" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |\n| D3 | docstring | \"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |\n| D4 | docstring | \"the three `videos_fts_*` triggers still exist\" | :119 | triggers lost in a rebuild | CARRIED |\n| D5 | docstring | \"a title MATCH still finds the preserved row\" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |\n| D6 | docstring | \"and a row inserted afterwards\" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |\n| D7 | docstring | \"a second run leaves `table_info`, the rows and the triggers identical\" | :128, :129, :130 | a non-idempotent second run | CARRIED |\n| D8a | docstring | \"`dist/videos-worker.js`, run under node against local PeerTube stand-ins\" | :188, :216, :224 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |\n| D8b | docstring | \"the committed `dist/videos-worker.js`\" | none | the dirty branch at :146-147 accepts an uncommitted dist on mtime alone, so nothing requires the dist to be committed | UNCARRIED |\n| D9 | docstring | \"`\"en\"` for a video carrying it\" | :224 | storing the label, or nothing | CARRIED |\n| D10 | docstring | \"NULL for `{\"id\": null}`\" | :224 | storing `\"Unknown\"` or the string `\"null\"` | CARRIED |\n| D11 | docstring | \"NULL for a video with no `language`\" | :224 (`\"b-1\": None`) | a crash or a stale value when the field is absent | CARRIED |\n| D12 | docstring | crawl.db seeded from `schema.sql` with the `language` line removed, \"so the table really lacks the column\" | :232, :246 | a seed that still has the column, which would make C2c vacuous | CARRIED |\n| D13 | docstring | \"the crawl adds the column\" | :256 | no migration of an existing crawl.db | CARRIED |\n| D14 | docstring | \"keeps the video it did not revisit with `language` NULL\" | :260 (`(\"a-0\", \"Old one\", None)`) | a column add that rebuilds the table and drops rows | CARRIED |\n| D15 | docstring | \"stores `\"de\"` on the one it did\" | :260 (`(\"a-1\", \"A one\", \"de\")`) | an upsert whose `ON CONFLICT` set omits `language` | CARRIED |\n| D16 | docstring | \"a missing node or git ... fails the test rather than skipping it\" | :153, :155 | a `pytest.skip` when a tool is missing | CARRIED |\n| D17 | docstring | \"a missing or stale dist ... fails the test\" | :157, :158 | running a missing or out-of-date build without complaint | CARRIED |\n| D18 | docstring | \"a nonzero node exit fails the test\" | :216, :252 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |\n| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |\n| N2 | name | `test_crawl_stores_each_videos_language` | :224 | a per-video value that is missing or shared | CARRIED |\n| N3 | name | `test_crawl_adds_language_to_existing_db` | :256, :260 | an existing crawl.db that is left without the column | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:1\n   D1b is UNCARRIED. The opening sentence says every videos table touched holds \"the PeerTube language code\". For the whitelist table the only value it ever holds is a hand-written `'fr'` (:121). No assertion shows a code crawled into crawl.db reaching whitelist `videos.language`, which is the job of `rebuild_content_tables` in sync-whitelist.py (listed as EDITED). Either assert that path or narrow the sentence. It is not in `must_prove`, so it does not block.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:4\n   D8b is UNCARRIED. The docstring says \"the committed `dist/videos-worker.js`\", but `_dist_is_stale` (:146-147) falls back to mtime when either file is dirty or uncommitted. An uncommitted dist therefore passes. Either require a committed, clean dist or drop \"committed\" from the sentence.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:127-130\n   Leftover gap in C1d (still CARRIED). After the second run the test checks table_info, five columns of each row, and the trigger names, but not the index. A second run that rebuilds `videos`, recreates the triggers and leaves `videos_fts` empty would pass. Re-running `_matches` after :127 would close this.\n4. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:199\n   `language` is tested present-with-id, `{\"id\": null}` and absent. Malformed shapes are not tested: `language` as a bare string, `language: null`, or a non-string `id`.\n5. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:99\n   `test_migration_adds_language_column` says what happens but not when: on a pre-change whitelist DB, keeping rows and triggers, idempotently. If the test fails on :128-130 (the second run), the runner output still names only \"adds language column\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js, tests/active/test_video_handler.py and tests/active/test_videos_worker.py. I did not read them. The crawl path was judged from engine/crawler/src/db.ts and src/videos-worker.ts, which the test requires the dist to be no older than (:156-158).\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines everything else itself, so I looked for no conftest.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB",
            "assertion": ":115",
            "excludes": "a migration that leaves `videos` without the column (the pre-state is confirmed at :109)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "keeps every row",
            "assertion": ":117",
            "excludes": "a rebuild that drops rows, or one that mis-maps the seeded title/tags_json/category values",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "keeps the three FTS triggers",
            "assertion": ":119",
            "excludes": "a rebuild of `videos` that drops `videos_fts_ai/ad/au` and does not recreate them (`migrate_videos_schema` drops them on rebuild)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "a second run changes nothing",
            "assertion": ":128, :129, :130",
            "excludes": "a second run that alters columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a crawl stores each video's PeerTube language code in crawl.db",
            "assertion": ":224",
            "excludes": "not storing the code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` next to a-2/b-1 NULL)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "NULL for a null id",
            "assertion": ":224 (`\"a-2\": None`)",
            "excludes": "storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "including in a crawl.db created before the column existed",
            "assertion": ":256, :260",
            "excludes": "a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"every videos table this build touches gains a nullable `language` column\"",
            "assertion": ":116, :224, :260",
            "excludes": "a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :224/:260)",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"...holding the PeerTube language code\", which includes the whitelist `videos` table",
            "assertion": "none",
            "excludes": "whitelist `language` only ever gets a hand-inserted `'fr'` at :121. Nothing shows a sync carrying a crawl.db code into it",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"adds a nullable `language` column\" (whitelist)",
            "assertion": ":115, :116",
            "excludes": "a missing column, or one declared NOT NULL",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\"",
            "assertion": ":117",
            "excludes": "dropped rows, shifted values, or a non-NULL default",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the three `videos_fts_*` triggers still exist\"",
            "assertion": ":119",
            "excludes": "triggers lost in a rebuild",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a title MATCH still finds the preserved row\"",
            "assertion": ":120",
            "excludes": "`videos_fts` dropped and recreated but never rebuilt from the content table",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"and a row inserted afterwards\"",
            "assertion": ":122",
            "excludes": "an insert trigger that exists by name but no longer feeds `videos_fts`",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a second run leaves `table_info`, the rows and the triggers identical\"",
            "assertion": ":128, :129, :130",
            "excludes": "a non-idempotent second run",
            "status": "CARRIED"
          },
          {
            "id": "D8a",
            "source": "docstring",
            "clause": "\"`dist/videos-worker.js`, run under node against local PeerTube stand-ins\"",
            "assertion": ":188, :216, :224",
            "excludes": "testing the TS source or a mock in place of the dist the crawl actually runs",
            "status": "CARRIED"
          },
          {
            "id": "D8b",
            "source": "docstring",
            "clause": "\"the committed `dist/videos-worker.js`\"",
            "assertion": "none",
            "excludes": "the dirty branch at :146-147 accepts an uncommitted dist on mtime alone, so nothing requires the dist to be committed",
            "status": "UNCARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`\"en\"` for a video carrying it\"",
            "assertion": ":224",
            "excludes": "storing the label, or nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"NULL for `{\"id\": null}`\"",
            "assertion": ":224",
            "excludes": "storing `\"Unknown\"` or the string `\"null\"`",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"NULL for a video with no `language`\"",
            "assertion": ":224 (`\"b-1\": None`)",
            "excludes": "a crash or a stale value when the field is absent",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "crawl.db seeded from `schema.sql` with the `language` line removed, \"so the table really lacks the column\"",
            "assertion": ":232, :246",
            "excludes": "a seed that still has the column, which would make C2c vacuous",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the crawl adds the column\"",
            "assertion": ":256",
            "excludes": "no migration of an existing crawl.db",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"keeps the video it did not revisit with `language` NULL\"",
            "assertion": ":260 (`(\"a-0\", \"Old one\", None)`)",
            "excludes": "a column add that rebuilds the table and drops rows",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"stores `\"de\"` on the one it did\"",
            "assertion": ":260 (`(\"a-1\", \"A one\", \"de\")`)",
            "excludes": "an upsert whose `ON CONFLICT` set omits `language`",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"a missing node or git ... fails the test rather than skipping it\"",
            "assertion": ":153, :155",
            "excludes": "a `pytest.skip` when a tool is missing",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a missing or stale dist ... fails the test\"",
            "assertion": ":157, :158",
            "excludes": "running a missing or out-of-date build without complaint",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"a nonzero node exit fails the test\"",
            "assertion": ":216, :252",
            "excludes": "ignoring a crashed crawl and reading whatever is left in the DB",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_migration_adds_language_column`",
            "assertion": ":115",
            "excludes": "a migration that adds nothing",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_crawl_stores_each_videos_language`",
            "assertion": ":224",
            "excludes": "a per-video value that is missing or shared",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`test_crawl_adds_language_to_existing_db`",
            "assertion": ":256, :260",
            "excludes": "an existing crawl.db that is left without the column",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_migration_adds_language_column fails at line 115 on `assert len(language) == 1`,\nbecause migrate_whitelist_schema (whitelist_migrations.py:373-377) only runs the\ninstances, channels and videos error-column rebuilds, and nothing adds `language`.\ntest_crawl_stores_each_videos_language fails at line 221 on\n`assert \"language\" in _column_names(conn)`. test_crawl_adds_language_to_existing_db\nfails at line 257 on the same column check. Both crawl failures follow from the fact\nthat no file under engine/ mentions `language` (schema.sql, db.ts, videos-worker.ts\nand both dist files included). Either crawl test fails earlier, at line 158 or 159,\nif a dist file is missing or older than its source.\n\nNOT ASSESSED\n1. `code_under_test` engine/crawler/src/db.ts, src/videos-worker.ts, dist/db.js,\n   dist/videos-worker.js and schema.sql were not read in full. The only checks run on\n   them were that `crawlVideos` is exported (videos-worker.ts:136, dist/videos-worker.js:15)\n   and a grep for `language`, which found no match under engine/.\n   tests/active/test_video_handler.py and tests/active/test_videos_worker.py were not\n   read. Neither is imported by the audited test.\n2. Whether the dist files are currently newer than their sources could not be checked\n   without running git. So it is not settled whether the crawl tests go red at line 159\n   or at the column checks.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |\n| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or maps the seeded title/tags_json/category values to the wrong columns | CARRIED |\n| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and never recreates them (the pre-state is confirmed at :110) | CARRIED |\n| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that changes columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |\n| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :225 | storing no code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` sits next to a-2/b-1 NULL) | CARRIED |\n| C2b | must_prove | NULL for a null id | :225 (`\"a-2\": None`) | storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code | CARRIED |\n| C2c | must_prove | including in a crawl.db created before the column existed | :257, :261 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |\n| D1a | docstring | \"The whitelist and crawl.db `videos` tables gain a nullable `language` column\" | :116, :225, :261 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :225/:261) | CARRIED |\n| D1b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D2 | docstring | \"adds a nullable `language` column\" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |\n| D3 | docstring | \"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |\n| D4 | docstring | \"the three `videos_fts_*` triggers still exist\" | :119 | triggers lost in a rebuild | CARRIED |\n| D5 | docstring | \"a title MATCH still finds the preserved row\" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |\n| D6 | docstring | \"and a row inserted afterwards\" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |\n| D7 | docstring | \"a second run leaves `table_info`, the rows and the triggers identical\" | :128, :129, :130 | a second run that is not idempotent | CARRIED |\n| D8a | docstring | \"`dist/videos-worker.js` ... run under node against local PeerTube stand-ins\" | :189, :217, :225 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |\n| D8b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D9 | docstring | \"`\"en\"` for a video carrying it\" | :225 | storing the label, or nothing | CARRIED |\n| D10 | docstring | \"NULL for `{\"id\": null}`\" | :225 | storing `\"Unknown\"` or the string `\"null\"` | CARRIED |\n| D11 | docstring | \"NULL for a video with no `language`\" | :225 (`\"b-1\": None`) | a crash or a stale value when the field is absent | CARRIED |\n| D12 | docstring | crawl.db seeded from `schema.sql` with any `language` line removed, \"so the table really lacks the column\" | :233, :247 | a seed that still has the column, which would make C2c vacuous | CARRIED |\n| D13 | docstring | \"the crawl adds the column\" | :257 | an existing crawl.db that never gets the column | CARRIED |\n| D14 | docstring | \"keeps the video it did not revisit with `language` NULL\" | :261 (`(\"a-0\", \"Old one\", None)`) | a column add that rebuilds the table and drops rows | CARRIED |\n| D15 | docstring | \"stores `\"de\"` on the one it did\" | :261 (`(\"a-1\", \"A one\", \"de\")`) | an upsert whose `ON CONFLICT` set leaves out `language` | CARRIED |\n| D16 | docstring | \"A missing node or git ... fails the test rather than skipping it\" | :154, :156 | a `pytest.skip` when a tool is missing | CARRIED |\n| D17 | docstring | \"a missing or stale dist ... fails the test\" | :158, :159 | running a missing or out-of-date build without complaint | CARRIED |\n| D18 | docstring | \"a nonzero node exit fails the test\" | :217, :253 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |\n| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |\n| N2 | name | `test_crawl_stores_each_videos_language` | :225 | a per-video value that is missing or shared | CARRIED |\n| N3 | name | `test_crawl_adds_language_to_existing_db` | :257, :261 | an existing crawl.db left without the column | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:1\n   D1b was closed by narrowing the prose, not by adding an assertion. The docstring used to say every `videos` table touched holds the PeerTube language code. It now says only \"a crawl fills crawl.db's with the PeerTube language code\", which :225 carries. The test still does not show a crawl.db code reaching the whitelist `videos.language`: the only value there is the hand-inserted `'fr'` at :121. `must_prove` C1 does not claim the whitelist column is filled, so no clause is left uncarried.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:4\n   D8b was also closed by narrowing the prose. \"the committed `dist/videos-worker.js`\" is now \"The built `dist/videos-worker.js`, no older than its source\". Line :159 carries that new clause: `_dist_is_stale` compares commit times for a clean tree and mtimes otherwise (:147-149), so a stale dist fails either way. The check at :157-159 also covers `dist/db.js`, which the docstring does not mention.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:200\n   The crawl covers three `language` shapes: an id is present, the id is null, and the field is absent. No test covers a malformed one, such as a bare string `\"language\": \"en\"`, a non-string id, or `language: null`. So nothing shows the worker stores NULL instead of crashing or writing a non-code value when the payload is malformed. The ledger names no row for this.\n\nNOT ASSESSED\n1. `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are listed in `code_under_test`, but this test does not exercise them, so I did not read them.\n2. I searched `engine/crawler/src/*.ts`, `engine/crawler/dist/*.js` and `engine/crawler/schema.sql` rather than reading them in full. I checked that `crawlVideos` exists and that the `instances`/`channels` columns the test seeds are defined. I did not check that the `LANGUAGE_LINE` strip at :232 leaves valid SQL, because the column's placement in `schema.sql` could not be seen. If it doesn't, :241 would raise and the test would fail rather than pass vacuously.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_migration_adds_language_column fails at line 115 on `assert len(language) == 1`,\nbecause migrate_whitelist_schema (whitelist_migrations.py:373-377) only runs the\ninstances, channels and videos error-column rebuilds, and nothing adds `language`.\ntest_crawl_stores_each_videos_language fails at line 221 on\n`assert \"language\" in _column_names(conn)`. test_crawl_adds_language_to_existing_db\nfails at line 257 on the same column check. Both crawl failures follow from the fact\nthat no file under engine/ mentions `language` (schema.sql, db.ts, videos-worker.ts\nand both dist files included). Either crawl test fails earlier, at line 158 or 159,\nif a dist file is missing or older than its source.\n\nNOT ASSESSED\n1. `code_under_test` engine/crawler/src/db.ts, src/videos-worker.ts, dist/db.js,\n   dist/videos-worker.js and schema.sql were not read in full. The only checks run on\n   them were that `crawlVideos` is exported (videos-worker.ts:136, dist/videos-worker.js:15)\n   and a grep for `language`, which found no match under engine/.\n   tests/active/test_video_handler.py and tests/active/test_videos_worker.py were not\n   read. Neither is imported by the audited test.\n2. Whether the dist files are currently newer than their sources could not be checked\n   without running git. So it is not settled whether the crawl tests go red at line 159\n   or at the column checks.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |\n| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or maps the seeded title/tags_json/category values to the wrong columns | CARRIED |\n| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and never recreates them (the pre-state is confirmed at :110) | CARRIED |\n| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that changes columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |\n| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :225 | storing no code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` sits next to a-2/b-1 NULL) | CARRIED |\n| C2b | must_prove | NULL for a null id | :225 (`\"a-2\": None`) | storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code | CARRIED |\n| C2c | must_prove | including in a crawl.db created before the column existed | :257, :261 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |\n| D1a | docstring | \"The whitelist and crawl.db `videos` tables gain a nullable `language` column\" | :116, :225, :261 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :225/:261) | CARRIED |\n| D1b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D2 | docstring | \"adds a nullable `language` column\" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |\n| D3 | docstring | \"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |\n| D4 | docstring | \"the three `videos_fts_*` triggers still exist\" | :119 | triggers lost in a rebuild | CARRIED |\n| D5 | docstring | \"a title MATCH still finds the preserved row\" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |\n| D6 | docstring | \"and a row inserted afterwards\" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |\n| D7 | docstring | \"a second run leaves `table_info`, the rows and the triggers identical\" | :128, :129, :130 | a second run that is not idempotent | CARRIED |\n| D8a | docstring | \"`dist/videos-worker.js` ... run under node against local PeerTube stand-ins\" | :189, :217, :225 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |\n| D8b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D9 | docstring | \"`\"en\"` for a video carrying it\" | :225 | storing the label, or nothing | CARRIED |\n| D10 | docstring | \"NULL for `{\"id\": null}`\" | :225 | storing `\"Unknown\"` or the string `\"null\"` | CARRIED |\n| D11 | docstring | \"NULL for a video with no `language`\" | :225 (`\"b-1\": None`) | a crash or a stale value when the field is absent | CARRIED |\n| D12 | docstring | crawl.db seeded from `schema.sql` with any `language` line removed, \"so the table really lacks the column\" | :233, :247 | a seed that still has the column, which would make C2c vacuous | CARRIED |\n| D13 | docstring | \"the crawl adds the column\" | :257 | an existing crawl.db that never gets the column | CARRIED |\n| D14 | docstring | \"keeps the video it did not revisit with `language` NULL\" | :261 (`(\"a-0\", \"Old one\", None)`) | a column add that rebuilds the table and drops rows | CARRIED |\n| D15 | docstring | \"stores `\"de\"` on the one it did\" | :261 (`(\"a-1\", \"A one\", \"de\")`) | an upsert whose `ON CONFLICT` set leaves out `language` | CARRIED |\n| D16 | docstring | \"A missing node or git ... fails the test rather than skipping it\" | :154, :156 | a `pytest.skip` when a tool is missing | CARRIED |\n| D17 | docstring | \"a missing or stale dist ... fails the test\" | :158, :159 | running a missing or out-of-date build without complaint | CARRIED |\n| D18 | docstring | \"a nonzero node exit fails the test\" | :217, :253 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |\n| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |\n| N2 | name | `test_crawl_stores_each_videos_language` | :225 | a per-video value that is missing or shared | CARRIED |\n| N3 | name | `test_crawl_adds_language_to_existing_db` | :257, :261 | an existing crawl.db left without the column | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:1\n   D1b was closed by narrowing the prose, not by adding an assertion. The docstring used to say every `videos` table touched holds the PeerTube language code. It now says only \"a crawl fills crawl.db's with the PeerTube language code\", which :225 carries. The test still does not show a crawl.db code reaching the whitelist `videos.language`: the only value there is the hand-inserted `'fr'` at :121. `must_prove` C1 does not claim the whitelist column is filled, so no clause is left uncarried.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:4\n   D8b was also closed by narrowing the prose. \"the committed `dist/videos-worker.js`\" is now \"The built `dist/videos-worker.js`, no older than its source\". Line :159 carries that new clause: `_dist_is_stale` compares commit times for a clean tree and mtimes otherwise (:147-149), so a stale dist fails either way. The check at :157-159 also covers `dist/db.js`, which the docstring does not mention.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase1.py:200\n   The crawl covers three `language` shapes: an id is present, the id is null, and the field is absent. No test covers a malformed one, such as a bare string `\"language\": \"en\"`, a non-string id, or `language: null`. So nothing shows the worker stores NULL instead of crashing or writing a non-code value when the payload is malformed. The ledger names no row for this.\n\nNOT ASSESSED\n1. `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are listed in `code_under_test`, but this test does not exercise them, so I did not read them.\n2. I searched `engine/crawler/src/*.ts`, `engine/crawler/dist/*.js` and `engine/crawler/schema.sql` rather than reading them in full. I checked that `crawlVideos` exists and that the `instances`/`channels` columns the test seeds are defined. I did not check that the `LANGUAGE_LINE` strip at :232 leaves valid SQL, because the column's placement in `schema.sql` could not be seen. If it doesn't, :241 would raise and the test would fail rather than pass vacuously.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB",
            "assertion": ":115",
            "excludes": "a migration that leaves `videos` without the column (the pre-state is confirmed at :109)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "keeps every row",
            "assertion": ":117",
            "excludes": "a rebuild that drops rows, or maps the seeded title/tags_json/category values to the wrong columns",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "keeps the three FTS triggers",
            "assertion": ":119",
            "excludes": "a rebuild of `videos` that drops `videos_fts_ai/ad/au` and never recreates them (the pre-state is confirmed at :110)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "a second run changes nothing",
            "assertion": ":128, :129, :130",
            "excludes": "a second run that changes columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a crawl stores each video's PeerTube language code in crawl.db",
            "assertion": ":225",
            "excludes": "storing no code, storing `label` instead of `id`, or storing one value for every video (a-1 `\"en\"` sits next to a-2/b-1 NULL)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "NULL for a null id",
            "assertion": ":225 (`\"a-2\": None`)",
            "excludes": "storing `\"null\"`, the `\"Unknown\"` label, or a neighbour's code",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "including in a crawl.db created before the column existed",
            "assertion": ":257, :261",
            "excludes": "a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"The whitelist and crawl.db `videos` tables gain a nullable `language` column\"",
            "assertion": ":116, :225, :261",
            "excludes": "a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :225/:261)",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"adds a nullable `language` column\" (whitelist)",
            "assertion": ":115, :116",
            "excludes": "a missing column, or one declared NOT NULL",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL\"",
            "assertion": ":117",
            "excludes": "dropped rows, shifted values, or a non-NULL default",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the three `videos_fts_*` triggers still exist\"",
            "assertion": ":119",
            "excludes": "triggers lost in a rebuild",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a title MATCH still finds the preserved row\"",
            "assertion": ":120",
            "excludes": "`videos_fts` dropped and recreated but never rebuilt from the content table",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"and a row inserted afterwards\"",
            "assertion": ":122",
            "excludes": "an insert trigger that exists by name but no longer feeds `videos_fts`",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a second run leaves `table_info`, the rows and the triggers identical\"",
            "assertion": ":128, :129, :130",
            "excludes": "a second run that is not idempotent",
            "status": "CARRIED"
          },
          {
            "id": "D8a",
            "source": "docstring",
            "clause": "\"`dist/videos-worker.js` ... run under node against local PeerTube stand-ins\"",
            "assertion": ":189, :217, :225",
            "excludes": "testing the TS source or a mock in place of the dist the crawl actually runs",
            "status": "CARRIED"
          },
          {
            "id": "D8b",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`\"en\"` for a video carrying it\"",
            "assertion": ":225",
            "excludes": "storing the label, or nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"NULL for `{\"id\": null}`\"",
            "assertion": ":225",
            "excludes": "storing `\"Unknown\"` or the string `\"null\"`",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"NULL for a video with no `language`\"",
            "assertion": ":225 (`\"b-1\": None`)",
            "excludes": "a crash or a stale value when the field is absent",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "crawl.db seeded from `schema.sql` with any `language` line removed, \"so the table really lacks the column\"",
            "assertion": ":233, :247",
            "excludes": "a seed that still has the column, which would make C2c vacuous",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the crawl adds the column\"",
            "assertion": ":257",
            "excludes": "an existing crawl.db that never gets the column",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"keeps the video it did not revisit with `language` NULL\"",
            "assertion": ":261 (`(\"a-0\", \"Old one\", None)`)",
            "excludes": "a column add that rebuilds the table and drops rows",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"stores `\"de\"` on the one it did\"",
            "assertion": ":261 (`(\"a-1\", \"A one\", \"de\")`)",
            "excludes": "an upsert whose `ON CONFLICT` set leaves out `language`",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"A missing node or git ... fails the test rather than skipping it\"",
            "assertion": ":154, :156",
            "excludes": "a `pytest.skip` when a tool is missing",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a missing or stale dist ... fails the test\"",
            "assertion": ":158, :159",
            "excludes": "running a missing or out-of-date build without complaint",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"a nonzero node exit fails the test\"",
            "assertion": ":217, :253",
            "excludes": "ignoring a crashed crawl and reading whatever is left in the DB",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_migration_adds_language_column`",
            "assertion": ":115",
            "excludes": "a migration that adds nothing",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_crawl_stores_each_videos_language`",
            "assertion": ":225",
            "excludes": "a per-video value that is missing or shared",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`test_crawl_adds_language_to_existing_db`",
            "assertion": ":257, :261",
            "excludes": "an existing crawl.db left without the column",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_10_video_metadata_completeness_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery case of test_response_labels fails at line 82 because `body.get(\"category\", \"MISSING\")`\nreturns \"MISSING\": the `response` dict built in handle_video_request (video.py:271-290) has no\n\"category\" key yet. test_refresh_stores_raw_codes gets past lines 102-103 (title updated,\nrow keeps \"15\"/\"en\") and fails at line 104 for the same reason: `body.get(\"category\", \"MISSING\")`\ngives \"MISSING\", not \"Science & Technology\".\n\nNOT ASSESSED\n1. `code_under_test` listed engine/server/data/peertube_labels.py (NEW), which is not there yet,\n   so I could not read it. The test does not import it and reaches it only through\n   handlers.video. I answered the stub question from the assertion form and the handler.\n2. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which is not there\n   either, so I could not read it. It is not the test under audit, and I made no finding from it.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 5 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a stored digit-only category id is answered with its PeerTube default label | :82 (`15`, `18` rows) | returning the stored id unchanged, and a label table that stops short of the top of the 1-18 range | CARRIED |\n| C1b | must_prove | an unknown id is answered as stored | :82 (`99`, `19` rows) | mapping an unknown id to empty, None or a placeholder, and an off-by-one table that resolves 19 | CARRIED |\n| C1c | must_prove | a text category is answered as stored | :82 (`Music` row) | nulling or relabelling a category that is not digits | CARRIED |\n| C2a | must_prove | a stored language code is answered with its PeerTube default label | :83 (`en`, `zh-Hans` rows) | returning the raw code, and a lookup on the primary subtag only that answers `zh-Hans` as plain \"Chinese\" | CARRIED |\n| C2b | must_prove | an unknown code is answered raw | :83 (`xx` rows) | mapping an unknown code to empty, None or a placeholder | CARRIED |\n| D1 | docstring | \"answers the stored category ... as PeerTube default display labels\" | :82 | a response with no category field (the `\"MISSING\"` default fails) or the raw id | CARRIED |\n| D2 | docstring | \"answers the stored ... language as PeerTube default display labels\" | :83 | a response with no language field, or the raw code | CARRIED |\n| D3 | docstring | \"leaves the stored id and code as they were\" | :103 | writing the label into `videos.category` / `videos.language` | CARRIED |\n| D4 | docstring | fetch failing: \"15\" answers \"Science & Technology\", \"18\" answers \"Food\" | :82 | raw passthrough, and a truncated table | CARRIED |\n| D5 | docstring | unknown id (\"99\", \"19\") or text category (\"Music\") answers as stored | :82 | replacing unmapped values | CARRIED |\n| D6 | docstring | \"en\" answers \"English\", \"zh-Hans\" answers \"Simplified Chinese\" | :83 | raw passthrough, and subtag-truncated lookup | CARRIED |\n| D7 | docstring | unknown code (\"xx\") answers \"xx\" | :83 | replacing an unmapped code | CARRIED |\n| D8 | docstring | a successful refresh with an id-only category and a code-only language \"writes the row\" | :102 | a refresh path that skips the UPDATE (title stays \"Old title\", last_checked_at stays 1000) | CARRIED |\n| D9 | docstring | refresh \"keeps '15' and 'en' stored\" | :103 | persisting the label, or nulling the id when the source has no label | CARRIED |\n| D10 | docstring | refresh \"answers 'Science & Technology' and 'English'\" | :104, :105 | a refresh path whose response bypasses the label mapping | CARRIED |\n| D11 | docstring | \"DB is built by `sync-whitelist.py`'s own schema helpers\" | :46-47 (by construction) | a hand-written schema that drifts from production | CARRIED |\n| D12 | docstring | \"the instance is never contacted\" | :75, :93 (by construction) | a real fetch: `fetch_instance_json` is replaced outright, and video.py has no other `urlopen` path | CARRIED |\n| N1 | name | `test_response_labels`: the response carries labels | :82, :83 | a response without labels | CARRIED |\n| N2 | name | `test_refresh_stores_raw_codes`: the refresh stores raw codes | :103 | a refresh that stores labels | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:58-68\n   The top of the 1-18 category range is tested (`18` resolves, `19` does not), but the bottom is not: `1` and `0` never run. The shapes that still count as \"digit-only\" are also untested: `\"015\"`, `\"\"`, and a NULL `category` or `language` column. C1's claim is about digit-only ids, so these are the edges that decide what counts as an id.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:70\n   No case stores a NULL category or language, so nothing shows how a missing stored value is answered. The fixture row at :50 always holds values, and every parametrised row overwrites both with non-empty strings.\n3. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:70, :86\n   `test_response_labels` and `test_refresh_stores_raw_codes` are noun phrases, not sentences saying what should happen and when. An example would be \"answers stored category id and language code as default labels when the instance fetch fails\". The parametrise ids at :68 carry some of the \"when\", but the names do not.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed engine/server/data/peertube_labels.py, which does not resolve (no match anywhere in the tree). I could not check the label table the test's expected values are meant to match, such as `18` \u2192 \"Food\" or `zh-Hans` \u2192 \"Simplified Chinese\". Bounds were judged from the test's own comment that the range is 1-18 (:64).\n2. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve. I could not assess what was edited there.\n3. engine/server/api/handlers/video.py was read as it currently stands. It has no label mapping and puts no `language` field in the response. Accepted inputs and failure behaviour were judged from that version, not the edited one.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery case of test_response_labels fails at line 82 because `body.get(\"category\", \"MISSING\")`\nreturns \"MISSING\": the `response` dict built in handle_video_request (video.py:271-290) has no\n\"category\" key yet. test_refresh_stores_raw_codes gets past lines 102-103 (title updated,\nrow keeps \"15\"/\"en\") and fails at line 104 for the same reason: `body.get(\"category\", \"MISSING\")`\ngives \"MISSING\", not \"Science & Technology\".\n\nNOT ASSESSED\n1. `code_under_test` listed engine/server/data/peertube_labels.py (NEW), which is not there yet,\n   so I could not read it. The test does not import it and reaches it only through\n   handlers.video. I answered the stub question from the assertion form and the handler.\n2. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which is not there\n   either, so I could not read it. It is not the test under audit, and I made no finding from it.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 5 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a stored digit-only category id is answered with its PeerTube default label | :82 (`15`, `18` rows) | returning the stored id unchanged, and a label table that stops short of the top of the 1-18 range | CARRIED |\n| C1b | must_prove | an unknown id is answered as stored | :82 (`99`, `19` rows) | mapping an unknown id to empty, None or a placeholder, and an off-by-one table that resolves 19 | CARRIED |\n| C1c | must_prove | a text category is answered as stored | :82 (`Music` row) | nulling or relabelling a category that is not digits | CARRIED |\n| C2a | must_prove | a stored language code is answered with its PeerTube default label | :83 (`en`, `zh-Hans` rows) | returning the raw code, and a lookup on the primary subtag only that answers `zh-Hans` as plain \"Chinese\" | CARRIED |\n| C2b | must_prove | an unknown code is answered raw | :83 (`xx` rows) | mapping an unknown code to empty, None or a placeholder | CARRIED |\n| D1 | docstring | \"answers the stored category ... as PeerTube default display labels\" | :82 | a response with no category field (the `\"MISSING\"` default fails) or the raw id | CARRIED |\n| D2 | docstring | \"answers the stored ... language as PeerTube default display labels\" | :83 | a response with no language field, or the raw code | CARRIED |\n| D3 | docstring | \"leaves the stored id and code as they were\" | :103 | writing the label into `videos.category` / `videos.language` | CARRIED |\n| D4 | docstring | fetch failing: \"15\" answers \"Science & Technology\", \"18\" answers \"Food\" | :82 | raw passthrough, and a truncated table | CARRIED |\n| D5 | docstring | unknown id (\"99\", \"19\") or text category (\"Music\") answers as stored | :82 | replacing unmapped values | CARRIED |\n| D6 | docstring | \"en\" answers \"English\", \"zh-Hans\" answers \"Simplified Chinese\" | :83 | raw passthrough, and subtag-truncated lookup | CARRIED |\n| D7 | docstring | unknown code (\"xx\") answers \"xx\" | :83 | replacing an unmapped code | CARRIED |\n| D8 | docstring | a successful refresh with an id-only category and a code-only language \"writes the row\" | :102 | a refresh path that skips the UPDATE (title stays \"Old title\", last_checked_at stays 1000) | CARRIED |\n| D9 | docstring | refresh \"keeps '15' and 'en' stored\" | :103 | persisting the label, or nulling the id when the source has no label | CARRIED |\n| D10 | docstring | refresh \"answers 'Science & Technology' and 'English'\" | :104, :105 | a refresh path whose response bypasses the label mapping | CARRIED |\n| D11 | docstring | \"DB is built by `sync-whitelist.py`'s own schema helpers\" | :46-47 (by construction) | a hand-written schema that drifts from production | CARRIED |\n| D12 | docstring | \"the instance is never contacted\" | :75, :93 (by construction) | a real fetch: `fetch_instance_json` is replaced outright, and video.py has no other `urlopen` path | CARRIED |\n| N1 | name | `test_response_labels`: the response carries labels | :82, :83 | a response without labels | CARRIED |\n| N2 | name | `test_refresh_stores_raw_codes`: the refresh stores raw codes | :103 | a refresh that stores labels | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:58-68\n   The top of the 1-18 category range is tested (`18` resolves, `19` does not), but the bottom is not: `1` and `0` never run. The shapes that still count as \"digit-only\" are also untested: `\"015\"`, `\"\"`, and a NULL `category` or `language` column. C1's claim is about digit-only ids, so these are the edges that decide what counts as an id.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:70\n   No case stores a NULL category or language, so nothing shows how a missing stored value is answered. The fixture row at :50 always holds values, and every parametrised row overwrites both with non-empty strings.\n3. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase2.py:70, :86\n   `test_response_labels` and `test_refresh_stores_raw_codes` are noun phrases, not sentences saying what should happen and when. An example would be \"answers stored category id and language code as default labels when the instance fetch fails\". The parametrise ids at :68 carry some of the \"when\", but the names do not.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed engine/server/data/peertube_labels.py, which does not resolve (no match anywhere in the tree). I could not check the label table the test's expected values are meant to match, such as `18` \u2192 \"Food\" or `zh-Hans` \u2192 \"Simplified Chinese\". Bounds were judged from the test's own comment that the range is 1-18 (:64).\n2. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve. I could not assess what was edited there.\n3. engine/server/api/handlers/video.py was read as it currently stands. It has no label mapping and puts no `language` field in the response. Accepted inputs and failure behaviour were judged from that version, not the edited one.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a stored digit-only category id is answered with its PeerTube default label",
            "assertion": ":82 (`15`, `18` rows)",
            "excludes": "returning the stored id unchanged, and a label table that stops short of the top of the 1-18 range",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "an unknown id is answered as stored",
            "assertion": ":82 (`99`, `19` rows)",
            "excludes": "mapping an unknown id to empty, None or a placeholder, and an off-by-one table that resolves 19",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a text category is answered as stored",
            "assertion": ":82 (`Music` row)",
            "excludes": "nulling or relabelling a category that is not digits",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a stored language code is answered with its PeerTube default label",
            "assertion": ":83 (`en`, `zh-Hans` rows)",
            "excludes": "returning the raw code, and a lookup on the primary subtag only that answers `zh-Hans` as plain \"Chinese\"",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "an unknown code is answered raw",
            "assertion": ":83 (`xx` rows)",
            "excludes": "mapping an unknown code to empty, None or a placeholder",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers the stored category ... as PeerTube default display labels\"",
            "assertion": ":82",
            "excludes": "a response with no category field (the `\"MISSING\"` default fails) or the raw id",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"answers the stored ... language as PeerTube default display labels\"",
            "assertion": ":83",
            "excludes": "a response with no language field, or the raw code",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"leaves the stored id and code as they were\"",
            "assertion": ":103",
            "excludes": "writing the label into `videos.category` / `videos.language`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "fetch failing: \"15\" answers \"Science & Technology\", \"18\" answers \"Food\"",
            "assertion": ":82",
            "excludes": "raw passthrough, and a truncated table",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "unknown id (\"99\", \"19\") or text category (\"Music\") answers as stored",
            "assertion": ":82",
            "excludes": "replacing unmapped values",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"en\" answers \"English\", \"zh-Hans\" answers \"Simplified Chinese\"",
            "assertion": ":83",
            "excludes": "raw passthrough, and subtag-truncated lookup",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "unknown code (\"xx\") answers \"xx\"",
            "assertion": ":83",
            "excludes": "replacing an unmapped code",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "a successful refresh with an id-only category and a code-only language \"writes the row\"",
            "assertion": ":102",
            "excludes": "a refresh path that skips the UPDATE (title stays \"Old title\", last_checked_at stays 1000)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "refresh \"keeps '15' and 'en' stored\"",
            "assertion": ":103",
            "excludes": "persisting the label, or nulling the id when the source has no label",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "refresh \"answers 'Science & Technology' and 'English'\"",
            "assertion": ":104, :105",
            "excludes": "a refresh path whose response bypasses the label mapping",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"DB is built by `sync-whitelist.py`'s own schema helpers\"",
            "assertion": ":46-47 (by construction)",
            "excludes": "a hand-written schema that drifts from production",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the instance is never contacted\"",
            "assertion": ":75, :93 (by construction)",
            "excludes": "a real fetch: `fetch_instance_json` is replaced outright, and video.py has no other `urlopen` path",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_response_labels`: the response carries labels",
            "assertion": ":82, :83",
            "excludes": "a response without labels",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_refresh_stores_raw_codes`: the refresh stores raw codes",
            "assertion": ":103",
            "excludes": "a refresh that stores labels",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_10_video_metadata_completeness_phase3.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_fetch_failure_leaves_db_untouched[urlopen-urlerror] and [status-404] should fail at line 149\n(`assert _snapshot(server.db) == before`). The row is written even when the fetch fails:\nfetch_instance_video_dynamic returns a non-empty dict of Nones, so `if dynamic` holds, which moves\n`last_checked_at` and sets `instances.last_error*` to NULL. The [not-json], [bad-utf8] and [json-list]\ncases should error at line 144, because JSONDecodeError, UnicodeDecodeError and\nAttributeError (`list.get`) escape `handle_video_request`. test_success_refreshes_row_and_response\nshould fail at line 167 on the row dict: `language` stays \"fr\" instead of \"en\", `duration` stays 10\ninstead of 321, and `thumbnail_url` keeps OLD_THUMBNAIL. The UPDATE never writes those columns.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve in this\n   worktree, so it was not read.\n2. `fixtures_path` was not supplied. The test defines its own `server` and `responses` fixtures and\n   otherwise uses only pytest built-ins (tmp_path, monkeypatch). The only conftest found,\n   tests/active/conftest.py, does not cover tests/tmp, so it was not read.\n```\n\nBasis for PASS (shape.md, read over tests/tmp/test_10_video_metadata_completeness_phase3.py):\n\n- **Anti-patterns pass:**\n  - No `.md` file is read and no substring assertions are made, so doc-lint-grep, section-scoped-substring-grep and whole-file-source-name-grep do not apply.\n  - hardcoded-spec-mirror: `ORIGINAL_KEYS` (line 44) is checked with a subset test against the handler's output (line 170), not against a code constant.\n  - tautological-assertion: every expected value is a literal or the independent seed (`before`). `popularity` and `last_checked_at` are left out of the comparison, not computed the way the code computes them, and `last_checked_at` gets its own `>` check (line 165).\n  - absence-only-assertion: the \"unchanged\" check in C1 (line 149) is paired with positive checks in the same test. Line 147 checks the fetch was attempted, and lines 150\u2013151 check the stored values in the response.\n  - echoed-literal: `handle_video_request` runs between every input and every assertion.\n  - single-value-pin: seeded values and source values differ on every asserted field (title, description, views, category, language fr/en, nsfw 0/1, duration 10/321/42, thumbnail, channel name, followers 3/9). The partial, empty-object and second-request tests show the output following the input across several inputs.\n- **Ladder pass:** Rung 1. The handler is called directly, with assertions on its captured response and on the database changes it makes. There is no CLI or subprocess boundary, so no higher rung applies. The test is not at a lower rung, so the downshift rule does not apply.\n- **Stub question:** The test would fail against a stub. The previous behaviour left as it was fails both C1 and C2 as predicted above. A hard-coded response fails too, because expected titles, views and tags differ across the parametrized cases and across the two requests (lines 229\u2013235). The `urlopen` mock sits below the real `fetch_instance_json`, so the real parsing runs. It does not let a stub pass.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (34 clauses: 11 must_prove, 17 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\" | :149 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :147 shows the fetch was attempted | CARRIED |\n| C1b | must_prove | \"a malformed detail body\" leaves the same values unchanged | :149 (404, not-json, bad-utf8, json-list params :138) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |\n| C1c | must_prove | \"the response answers the DB values\": the metadata fields | :150, :151 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |\n| C1d | must_prove | \"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3) | none | nothing. `STORED_ANSWER` (:45) leaves out all three, so a failure path that answers any value for them passes | UNCARRIED |\n| C2a | must_prove | \"writes the source value for each field present\": the videos row | :163, :165, :167 | any source field dropped, left at the seed or mis-mapped. Every column is compared against `{**before, ...}` | CARRIED |\n| C2b | must_prove | \"writes the source value for each field present\": the channels row | :168 | slug, display name or followers not written from the source | CARRIED |\n| C2c | must_prove | \"the DB value for each field absent\": the videos row | :194 (absent and null-or-blank params) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |\n| C2d | must_prove | \"the DB value for each field absent\": the channels row | none | nothing. No success-path test with an absent channel, or a failed channel-detail fetch, reads back the channels row | UNCARRIED |\n| C2e | must_prove | \"the response answers the same merged values\": present fields | :170, :172, :173 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |\n| C2f | must_prove | response answers the merged values: absent metadata fields | :196, :197 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |\n| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | none | nothing. `expected = {**STORED_ANSWER, \"views\": 77}` (:195) leaves them out, so the row (:194) and the response can disagree | UNCARRIED |\n| D1 | docstring | \"writes the stored video only when the detail fetch returns a JSON object\" | :149, :219 | writing on a non-object body, or not writing on an object body | CARRIED |\n| D2 | docstring | \"on success stores and answers one source-over-DB value set\" | :167, :172 | the row and the response diverging on present fields | CARRIED |\n| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :138 params, :149 | any listed kind treated as success | CARRIED |\n| D4 | docstring | \"leaves the whole videos row, every channels row and instances.last_error* as they were\" | :149 | a partial write on failure | CARRIED |\n| D5 | docstring | \"answers 200 with the stored title, description, views, tags, category, language, nsfw, duration, thumbnail and channel name\" | :129, :150, :151 | a non-200 reply, or any named field not the stored value | CARRIED |\n| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :163, :167, :168 | any named field not written, or a relative thumbnail stored | CARRIED |\n| D7 | docstring | \"moves last_checked_at forward\" | :165 | `last_checked_at` left unchanged | CARRIED |\n| D8 | docstring | \"clears instances.last_error*\" | :169 | the seeded error left in place | CARRIED |\n| D9 | docstring | \"leaves every other column as seeded\" | :167 | a write to a column outside the mapping | CARRIED |\n| D10 | docstring | \"keeps the 18 original response keys\" | :170 | an original key dropped | CARRIED |\n| D11 | docstring | \"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\" | :172, :173 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |\n| D12 | docstring | omitted, null, blank or null-language-id field \"keeps the stored value in the row\" | :194 | overwriting with NULL or blank | CARRIED |\n| D13a | docstring | \"... and in the response\": the fields named in STORED_ANSWER | :196, :197 | the response answering blanks for those fields | CARRIED |\n| D13b | docstring | \"... and in the response\": omitted likes and dislikes | none | nothing, same gap as C2g | UNCARRIED |\n| D14 | docstring | \"`tags: []` stores \"[]\" and answers `[]`\" | :206, :207 | an empty list treated as absent (old tags kept) | CARRIED |\n| D15 | docstring | \"A JSON object body, `{}` included, counts as a success\" | :219, :220, :221 | `{}` treated as failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |\n| D16 | docstring | \"A source change between two requests is in the second response and in the row\" | :233, :235 | a cached or first-write-only value | CARRIED |\n| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :60-61, :75, :110 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:103) | CARRIED |\n| N1 | name | \"fetch failure leaves db untouched\" | :149 | a write on failure | CARRIED |\n| N2 | name | \"success refreshes row and response\" | :167, :172 | a stale row or response after success | CARRIED |\n| N3 | name | \"partial payload keeps tags and category\" | :194 | tags_json or category overwritten (both inside `before`) | CARRIED |\n| N4 | name | \"empty tag list propagates\" | :206, :207 | `[]` ignored | CARRIED |\n| N5 | name | \"object body counts as success\" | :219 | `{}` or an object body not written | CARRIED |\n| N6 | name | \"second request reflects source change\" | :233, :235 | the first fetch's values persisting | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:150\n   `assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1`\n   C1 says the failure response \"answers the DB values\". `STORED_ANSWER` (:45) leaves out `likes`, `dislikes` and `subscribersCount`, though the seed stores 1, 0 and 3 and the success test does assert them (:171). Nothing checks these three on the failure path, so an implementation that answers a default or `None` for them after a failed fetch passes. This is C1d.\n2. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:194\n   `assert after == {**before, \"views\": 77, \"popularity\": after[\"popularity\"], \"last_checked_at\": after[\"last_checked_at\"]}  # C2`\n   C2 says a successful fetch writes \"the DB value for each field absent\". This only checks the videos row. No success-path test reads back the channels row when the channel fields are absent: the partial and object payloads carry no `channel`, and no test fails the `/api/v1/video-channels/...` fetch while the detail fetch succeeds. An implementation that writes NULL slug, display name or followers into `channels` in that case passes. This is C2d.\n3. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:195\n   `expected = {**STORED_ANSWER, \"views\": 77}`\n   C2 says the response \"answers the same merged values\". On the absent-field path the response assertion leaves out `likes`, `dislikes` and `subscribersCount`, while :194 pins `likes` and `dislikes` in the row. A response that disagrees with the row it just wrote passes. This is C2g, and it also covers D13b.\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:42\n   No payload sends a present falsy value, such as `views: 0`, `likes: 0`, `nsfw: False` over a stored 1, or `duration: 0`. A merge written as `source or db` treats these as absent and passes every test here, so C2a's \"each field present\" is untested at zero.\n2. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:138\n   The malformed-body cases do not include an empty body `b\"\"`, a JSON `null`, or a JSON scalar (`b\"3\"`, `b'\"x\"'`). The caught-error cases cover `URLError` only. `TimeoutError`, which the fetch path catches alongside it, is not exercised.\n3. name-as-sentence (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:185\n   `test_partial_payload_keeps_tags_and_category` asserts that every column is kept (:194), and the response too. When description or duration regresses, the runner output names tags and category, so it does not tell the reader what broke.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_handler.py, which does not exist at this path. Nothing in it was read.\n2. `fixtures_path` was not supplied. The test defines its own fixtures (:55, :72), and the only conftest found (tests/active/conftest.py) does not cover tests/tmp/. No outside fixture was needed.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_fetch_failure_leaves_db_untouched[urlopen-urlerror] and [status-404] should fail at line 149\n(`assert _snapshot(server.db) == before`). The row is written even when the fetch fails:\nfetch_instance_video_dynamic returns a non-empty dict of Nones, so `if dynamic` holds, which moves\n`last_checked_at` and sets `instances.last_error*` to NULL. The [not-json], [bad-utf8] and [json-list]\ncases should error at line 144, because JSONDecodeError, UnicodeDecodeError and\nAttributeError (`list.get`) escape `handle_video_request`. test_success_refreshes_row_and_response\nshould fail at line 167 on the row dict: `language` stays \"fr\" instead of \"en\", `duration` stays 10\ninstead of 321, and `thumbnail_url` keeps OLD_THUMBNAIL. The UPDATE never writes those columns.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve in this\n   worktree, so it was not read.\n2. `fixtures_path` was not supplied. The test defines its own `server` and `responses` fixtures and\n   otherwise uses only pytest built-ins (tmp_path, monkeypatch). The only conftest found,\n   tests/active/conftest.py, does not cover tests/tmp, so it was not read.\n```\n\nBasis for PASS (shape.md, read over tests/tmp/test_10_video_metadata_completeness_phase3.py):\n\n- **Anti-patterns pass:**\n  - No `.md` file is read and no substring assertions are made, so doc-lint-grep, section-scoped-substring-grep and whole-file-source-name-grep do not apply.\n  - hardcoded-spec-mirror: `ORIGINAL_KEYS` (line 44) is checked with a subset test against the handler's output (line 170), not against a code constant.\n  - tautological-assertion: every expected value is a literal or the independent seed (`before`). `popularity` and `last_checked_at` are left out of the comparison, not computed the way the code computes them, and `last_checked_at` gets its own `>` check (line 165).\n  - absence-only-assertion: the \"unchanged\" check in C1 (line 149) is paired with positive checks in the same test. Line 147 checks the fetch was attempted, and lines 150\u2013151 check the stored values in the response.\n  - echoed-literal: `handle_video_request` runs between every input and every assertion.\n  - single-value-pin: seeded values and source values differ on every asserted field (title, description, views, category, language fr/en, nsfw 0/1, duration 10/321/42, thumbnail, channel name, followers 3/9). The partial, empty-object and second-request tests show the output following the input across several inputs.\n- **Ladder pass:** Rung 1. The handler is called directly, with assertions on its captured response and on the database changes it makes. There is no CLI or subprocess boundary, so no higher rung applies. The test is not at a lower rung, so the downshift rule does not apply.\n- **Stub question:** The test would fail against a stub. The previous behaviour left as it was fails both C1 and C2 as predicted above. A hard-coded response fails too, because expected titles, views and tags differ across the parametrized cases and across the two requests (lines 229\u2013235). The `urlopen` mock sits below the real `fetch_instance_json`, so the real parsing runs. It does not let a stub pass.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (34 clauses: 11 must_prove, 17 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\" | :149 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :147 shows the fetch was attempted | CARRIED |\n| C1b | must_prove | \"a malformed detail body\" leaves the same values unchanged | :149 (404, not-json, bad-utf8, json-list params :138) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |\n| C1c | must_prove | \"the response answers the DB values\": the metadata fields | :150, :151 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |\n| C1d | must_prove | \"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3) | none | nothing. `STORED_ANSWER` (:45) leaves out all three, so a failure path that answers any value for them passes | UNCARRIED |\n| C2a | must_prove | \"writes the source value for each field present\": the videos row | :163, :165, :167 | any source field dropped, left at the seed or mis-mapped. Every column is compared against `{**before, ...}` | CARRIED |\n| C2b | must_prove | \"writes the source value for each field present\": the channels row | :168 | slug, display name or followers not written from the source | CARRIED |\n| C2c | must_prove | \"the DB value for each field absent\": the videos row | :194 (absent and null-or-blank params) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |\n| C2d | must_prove | \"the DB value for each field absent\": the channels row | none | nothing. No success-path test with an absent channel, or a failed channel-detail fetch, reads back the channels row | UNCARRIED |\n| C2e | must_prove | \"the response answers the same merged values\": present fields | :170, :172, :173 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |\n| C2f | must_prove | response answers the merged values: absent metadata fields | :196, :197 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |\n| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | none | nothing. `expected = {**STORED_ANSWER, \"views\": 77}` (:195) leaves them out, so the row (:194) and the response can disagree | UNCARRIED |\n| D1 | docstring | \"writes the stored video only when the detail fetch returns a JSON object\" | :149, :219 | writing on a non-object body, or not writing on an object body | CARRIED |\n| D2 | docstring | \"on success stores and answers one source-over-DB value set\" | :167, :172 | the row and the response diverging on present fields | CARRIED |\n| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :138 params, :149 | any listed kind treated as success | CARRIED |\n| D4 | docstring | \"leaves the whole videos row, every channels row and instances.last_error* as they were\" | :149 | a partial write on failure | CARRIED |\n| D5 | docstring | \"answers 200 with the stored title, description, views, tags, category, language, nsfw, duration, thumbnail and channel name\" | :129, :150, :151 | a non-200 reply, or any named field not the stored value | CARRIED |\n| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :163, :167, :168 | any named field not written, or a relative thumbnail stored | CARRIED |\n| D7 | docstring | \"moves last_checked_at forward\" | :165 | `last_checked_at` left unchanged | CARRIED |\n| D8 | docstring | \"clears instances.last_error*\" | :169 | the seeded error left in place | CARRIED |\n| D9 | docstring | \"leaves every other column as seeded\" | :167 | a write to a column outside the mapping | CARRIED |\n| D10 | docstring | \"keeps the 18 original response keys\" | :170 | an original key dropped | CARRIED |\n| D11 | docstring | \"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\" | :172, :173 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |\n| D12 | docstring | omitted, null, blank or null-language-id field \"keeps the stored value in the row\" | :194 | overwriting with NULL or blank | CARRIED |\n| D13a | docstring | \"... and in the response\": the fields named in STORED_ANSWER | :196, :197 | the response answering blanks for those fields | CARRIED |\n| D13b | docstring | \"... and in the response\": omitted likes and dislikes | none | nothing, same gap as C2g | UNCARRIED |\n| D14 | docstring | \"`tags: []` stores \"[]\" and answers `[]`\" | :206, :207 | an empty list treated as absent (old tags kept) | CARRIED |\n| D15 | docstring | \"A JSON object body, `{}` included, counts as a success\" | :219, :220, :221 | `{}` treated as failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |\n| D16 | docstring | \"A source change between two requests is in the second response and in the row\" | :233, :235 | a cached or first-write-only value | CARRIED |\n| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :60-61, :75, :110 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:103) | CARRIED |\n| N1 | name | \"fetch failure leaves db untouched\" | :149 | a write on failure | CARRIED |\n| N2 | name | \"success refreshes row and response\" | :167, :172 | a stale row or response after success | CARRIED |\n| N3 | name | \"partial payload keeps tags and category\" | :194 | tags_json or category overwritten (both inside `before`) | CARRIED |\n| N4 | name | \"empty tag list propagates\" | :206, :207 | `[]` ignored | CARRIED |\n| N5 | name | \"object body counts as success\" | :219 | `{}` or an object body not written | CARRIED |\n| N6 | name | \"second request reflects source change\" | :233, :235 | the first fetch's values persisting | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:150\n   `assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1`\n   C1 says the failure response \"answers the DB values\". `STORED_ANSWER` (:45) leaves out `likes`, `dislikes` and `subscribersCount`, though the seed stores 1, 0 and 3 and the success test does assert them (:171). Nothing checks these three on the failure path, so an implementation that answers a default or `None` for them after a failed fetch passes. This is C1d.\n2. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:194\n   `assert after == {**before, \"views\": 77, \"popularity\": after[\"popularity\"], \"last_checked_at\": after[\"last_checked_at\"]}  # C2`\n   C2 says a successful fetch writes \"the DB value for each field absent\". This only checks the videos row. No success-path test reads back the channels row when the channel fields are absent: the partial and object payloads carry no `channel`, and no test fails the `/api/v1/video-channels/...` fetch while the detail fetch succeeds. An implementation that writes NULL slug, display name or followers into `channels` in that case passes. This is C2d.\n3. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:195\n   `expected = {**STORED_ANSWER, \"views\": 77}`\n   C2 says the response \"answers the same merged values\". On the absent-field path the response assertion leaves out `likes`, `dislikes` and `subscribersCount`, while :194 pins `likes` and `dislikes` in the row. A response that disagrees with the row it just wrote passes. This is C2g, and it also covers D13b.\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:42\n   No payload sends a present falsy value, such as `views: 0`, `likes: 0`, `nsfw: False` over a stored 1, or `duration: 0`. A merge written as `source or db` treats these as absent and passes every test here, so C2a's \"each field present\" is untested at zero.\n2. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:138\n   The malformed-body cases do not include an empty body `b\"\"`, a JSON `null`, or a JSON scalar (`b\"3\"`, `b'\"x\"'`). The caught-error cases cover `URLError` only. `TimeoutError`, which the fetch path catches alongside it, is not exercised.\n3. name-as-sentence (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:185\n   `test_partial_payload_keeps_tags_and_category` asserts that every column is kept (:194), and the response too. When description or duration regresses, the runner output names tags and category, so it does not tell the reader what broke.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_handler.py, which does not exist at this path. Nothing in it was read.\n2. `fixtures_path` was not supplied. The test defines its own fixtures (:55, :72), and the only conftest found (tests/active/conftest.py) does not cover tests/tmp/. No outside fixture was needed.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\"",
            "assertion": ":149",
            "excludes": "a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :147 shows the fetch was attempted",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"a malformed detail body\" leaves the same values unchanged",
            "assertion": ":149 (404, not-json, bad-utf8, json-list params :138)",
            "excludes": "a non-200, non-JSON, non-UTF-8 or list body being treated as success and written",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"the response answers the DB values\": the metadata fields",
            "assertion": ":150, :151",
            "excludes": "the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3)",
            "assertion": "none",
            "excludes": "nothing. `STORED_ANSWER` (:45) leaves out all three, so a failure path that answers any value for them passes",
            "status": "UNCARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"writes the source value for each field present\": the videos row",
            "assertion": ":163, :165, :167",
            "excludes": "any source field dropped, left at the seed or mis-mapped. Every column is compared against `{**before, ...}`",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"writes the source value for each field present\": the channels row",
            "assertion": ":168",
            "excludes": "slug, display name or followers not written from the source",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"the DB value for each field absent\": the videos row",
            "assertion": ":194 (absent and null-or-blank params)",
            "excludes": "NULL or blank written over a stored value for an omitted, null or blank field",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"the DB value for each field absent\": the channels row",
            "assertion": "none",
            "excludes": "nothing. No success-path test with an absent channel, or a failed channel-detail fetch, reads back the channels row",
            "status": "UNCARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "\"the response answers the same merged values\": present fields",
            "assertion": ":170, :172, :173",
            "excludes": "the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "response answers the merged values: absent metadata fields",
            "assertion": ":196, :197",
            "excludes": "the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw",
            "status": "CARRIED"
          },
          {
            "id": "C2g",
            "source": "must_prove",
            "clause": "response answers the merged values: absent likes, dislikes, subscribersCount",
            "assertion": "none",
            "excludes": "nothing. `expected = {**STORED_ANSWER, \"views\": 77}` (:195) leaves them out, so the row (:194) and the response can disagree",
            "status": "UNCARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"writes the stored video only when the detail fetch returns a JSON object\"",
            "assertion": ":149, :219",
            "excludes": "writing on a non-object body, or not writing on an object body",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"on success stores and answers one source-over-DB value set\"",
            "assertion": ":167, :172",
            "excludes": "the row and the response diverging on present fields",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list",
            "assertion": ":138 params, :149",
            "excludes": "any listed kind treated as success",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"leaves the whole videos row, every channels row and instances.last_error* as they were\"",
            "assertion": ":149",
            "excludes": "a partial write on failure",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"answers 200 with the stored title, description, views, tags, category, language, nsfw, duration, thumbnail and channel name\"",
            "assertion": ":129, :150, :151",
            "excludes": "a non-200 reply, or any named field not the stored value",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "full payload writes title ... absolute thumbnail URL and the channel",
            "assertion": ":163, :167, :168",
            "excludes": "any named field not written, or a relative thumbnail stored",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"moves last_checked_at forward\"",
            "assertion": ":165",
            "excludes": "`last_checked_at` left unchanged",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"clears instances.last_error*\"",
            "assertion": ":169",
            "excludes": "the seeded error left in place",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"leaves every other column as seeded\"",
            "assertion": ":167",
            "excludes": "a write to a column outside the mapping",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"keeps the 18 original response keys\"",
            "assertion": ":170",
            "excludes": "an original key dropped",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\"",
            "assertion": ":172, :173",
            "excludes": "raw codes, a JSON string for tags, or 1/0 for nsfw",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "omitted, null, blank or null-language-id field \"keeps the stored value in the row\"",
            "assertion": ":194",
            "excludes": "overwriting with NULL or blank",
            "status": "CARRIED"
          },
          {
            "id": "D13a",
            "source": "docstring",
            "clause": "\"... and in the response\": the fields named in STORED_ANSWER",
            "assertion": ":196, :197",
            "excludes": "the response answering blanks for those fields",
            "status": "CARRIED"
          },
          {
            "id": "D13b",
            "source": "docstring",
            "clause": "\"... and in the response\": omitted likes and dislikes",
            "assertion": "none",
            "excludes": "nothing, same gap as C2g",
            "status": "UNCARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"`tags: []` stores \"[]\" and answers `[]`\"",
            "assertion": ":206, :207",
            "excludes": "an empty list treated as absent (old tags kept)",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"A JSON object body, `{}` included, counts as a success\"",
            "assertion": ":219, :220, :221",
            "excludes": "`{}` treated as failure: no `last_checked_at` bump, and the error is not cleared",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"A source change between two requests is in the second response and in the row\"",
            "assertion": ":233, :235",
            "excludes": "a cached or first-write-only value",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted",
            "assertion": ":60-61, :75, :110 (setup, not assertions)",
            "excludes": "a real network call. Unlisted paths raise `URLError` (:103)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"fetch failure leaves db untouched\"",
            "assertion": ":149",
            "excludes": "a write on failure",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"success refreshes row and response\"",
            "assertion": ":167, :172",
            "excludes": "a stale row or response after success",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"partial payload keeps tags and category\"",
            "assertion": ":194",
            "excludes": "tags_json or category overwritten (both inside `before`)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"empty tag list propagates\"",
            "assertion": ":206, :207",
            "excludes": "`[]` ignored",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"object body counts as success\"",
            "assertion": ":219",
            "excludes": "`{}` or an object body not written",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"second request reflects source change\"",
            "assertion": ":233, :235",
            "excludes": "the first fetch's values persisting",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No shape.md entry covers this: stub question, previous behaviour. Location: tests/tmp/test_10_video_metadata_completeness_phase3.py:211-212\n   `assert tuple(server.db.execute(\"SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'\").fetchone()) == (\"newslug\", \"New Chan\", 3)  # C2`\n   `test_failed_channel_fetch_keeps_stored_followers` passes against video.py as it stands. The current handler already falls back to `row[\"channel_followers_count\"]` when the channel-detail fetch fails. That fallback is correct for this case. A wrong implementation that wrote `None` or dropped the fallback would still fail here, so this is not a stub-pass. But this test will not be red in the observed run, and it does not gate the phase's change.\n\nPREDICTED FAILURE\nAgainst the code as it stands:\n- test_fetch_failure_leaves_db_untouched:\n  - [urlerror] and [status-404] fail at line 150 (`_snapshot(server.db) == before`). `dynamic` is a non-empty dict, so the handler writes anyway: it advances `last_checked_at` and `popularity` and sets `instances.last_error*` to NULL.\n  - [not-json], [bad-utf8] and [json-list] error at line 145. `fetch_instance_json` does not catch `JSONDecodeError` or `UnicodeDecodeError`, and a JSON list raises `AttributeError` on `detail.get`.\n- test_success_refreshes_row_and_response fails at line 168. The row keeps `language='fr'`, `duration=10` and the old `thumbnail_url`.\n- Both test_partial_payload_keeps_tags_and_category cases fail at line 199. The response has no `duration` or `thumbnailUrl` key, so each reads as \"MISSING\".\n- test_empty_tag_list_propagates fails at line 221. `to_tags_json([])` returns None, so `tags_json` stays `'[\"old\"]'`.\n- test_object_body_counts_as_success:\n  - [object] fails at line 234 because `duration` stays 10.\n  - [empty-object] fails at line 236 because `duration` is \"MISSING\" in the reply.\n- test_second_request_reflects_source_change fails at line 248 because `tags` is \"MISSING\" in both responses.\n- test_failed_channel_fetch_keeps_stored_followers passes (see Recommendation 1).\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which does not resolve (FileNotFoundError). Its edits were not read.\n2. `fixtures_path` was not supplied. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/. Every fixture the test uses (`server`, `responses`) is defined in the test file itself, so nothing was left unresolved.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (37 clauses: 11 must_prove, 20 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\" | :150 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :148 shows the fetch was attempted | CARRIED |\n| C1b | must_prove | \"a malformed detail body\" leaves the same values unchanged | :150 (404, not-json, bad-utf8, json-list params :139) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |\n| C1c | must_prove | \"the response answers the DB values\": the metadata fields | :151, :152 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |\n| C1d | must_prove | \"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3) | :151 | `STORED_ANSWER` (:46) now holds `\"likes\": 1, \"dislikes\": 0, ... \"subscribersCount\": 3`, so the test fails if the failure path answers any other value for these three | CARRIED |\n| C2a | must_prove | \"writes the source value for each field present\": the videos row | :164, :166, :168 | any source field dropped, left at the seed or mapped to the wrong column. Every column is compared against `{**before, ...}` | CARRIED |\n| C2b | must_prove | \"writes the source value for each field present\": the channels row | :169 | slug, display name or followers not written from the source | CARRIED |\n| C2c | must_prove | \"the DB value for each field absent\": the videos row | :196 (absent and null-or-blank params :180-182) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |\n| C2d | must_prove | \"the DB value for each field absent\": the channels row | :197, :211 | an absent `channel` rewriting the channels row (:197), or a failed channel-detail fetch writing NULL over the stored follower count of 3 (:211) | CARRIED |\n| C2e | must_prove | \"the response answers the same merged values\": present fields | :171, :173, :174 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |\n| C2f | must_prove | response answers the merged values: absent metadata fields | :199, :200 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |\n| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | :199 | `expected = {**STORED_ANSWER, \"views\": 77}` (:198) now includes 1, 0 and 3, so the test fails if the response disagrees with the row (:196) on these fields | CARRIED |\n| D1 | docstring | \"writes the stored video only when the detail fetch returns a JSON object\" | :150, :234 | writing on a non-object body, or not writing on an object body | CARRIED |\n| D2 | docstring | \"on success stores and answers one source-over-DB value set\" | :168, :173 | the row and the response disagreeing on present fields | CARRIED |\n| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :139 params, :150 | any listed kind treated as success | CARRIED |\n| D4 | docstring | \"leaves the whole videos row, every channels row and instances.last_error* as they were\" | :150 | a partial write on failure | CARRIED |\n| D5 | docstring | \"answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count\" | :130, :151, :152 | a non-200 reply, or any named field answered with something other than the stored value | CARRIED |\n| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :164, :168, :169 | any named field not written, or a relative thumbnail stored | CARRIED |\n| D7 | docstring | \"moves last_checked_at forward\" | :166 | `last_checked_at` left unchanged | CARRIED |\n| D8 | docstring | \"clears instances.last_error*\" | :170 | the seeded error left in place | CARRIED |\n| D9 | docstring | \"leaves every other column as seeded\" | :168 | a write to a column outside the mapping | CARRIED |\n| D10 | docstring | \"keeps the 18 original response keys\" | :171 | an original key dropped | CARRIED |\n| D11 | docstring | \"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\" | :173, :174 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |\n| D12 | docstring | omitted, null, blank or null-language-id field \"keeps the stored value in the row\" | :196 | overwriting with NULL or blank | CARRIED |\n| D13a | docstring | \"... and in the response\": the fields named in STORED_ANSWER | :199, :200 | the response answering blanks for those fields | CARRIED |\n| D13b | docstring | \"... and in the response\": omitted likes and dislikes | :199 | the response answering anything other than the stored 1 and 0. Both are now in `STORED_ANSWER` | CARRIED |\n| D14 | docstring | \"`tags: []` stores \"[]\" and answers `[]`\" | :221, :222 | an empty list treated as absent, so the old tags are kept | CARRIED |\n| D15 | docstring | \"A JSON object body, `{}` included, counts as a success\" | :234, :235, :236 | `{}` treated as a failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |\n| D16 | docstring | \"A source change between two requests is in the second response and in the row\" | :248, :250 | a cached value, or one written only on the first fetch | CARRIED |\n| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :61-62, :76, :111 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:104) | CARRIED |\n| N1 | name | \"fetch failure leaves db untouched\" | :150 | a write on failure | CARRIED |\n| N2 | name | \"success refreshes row and response\" | :168, :173 | a stale row or response after success | CARRIED |\n| N3 | name | \"partial payload keeps tags and category\" | :196 | tags_json or category overwritten (both are inside `before`) | CARRIED |\n| N4 | name | \"empty tag list propagates\" | :221, :222 | `[]` ignored | CARRIED |\n| N5 | name | \"object body counts as success\" | :234 | `{}` or another object body not written | CARRIED |\n| N6 | name | \"second request reflects source change\" | :248, :250 | the first fetch's values persisting | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase3.py:6, :212\n   New docstring sentence, not in the ledger: \"A failed channel-detail fetch writes the source channel slug and display name and keeps the stored follower count, in the channels row and in the response.\"\n   - The row half is carried at :211.\n   - In the response, :212 asserts `channelName` and `subscribersCount` only. The slug reaches the response only through `channelUrl`, and nothing asserts `channelUrl`.\n   - So the test still passes if the response builds `channelUrl` from the stored `oldslug` instead of the source `newslug`. The \"slug ... in the response\" part of this sentence is uncarried.\n   - The same gap is in the full-payload test. :173 does not assert `channelUrl` either, even though the channel slug is a present field under C2e.\n   - To fix this, assert `channelUrl` or narrow the sentence.\n2. Clauses added since the ledger that are carried, for the record:\n   - Docstring :5, \"and leaves the channels row as it was\", is carried at :197.\n   - The new test name `test_failed_channel_fetch_keeps_stored_followers` is carried at :211 and :212.\n   - D5's sentence was widened to add likes, dislikes and subscriber count, not narrowed. It is carried at :151.\n3. The round-one UNCARRIED rows C1d, C2d, C2g and D13b were fixed by new assertions, not by narrowing the prose:\n   - `STORED_ANSWER` was extended (:46).\n   - A channels-row check was added at :197.\n   - A new failed-channel-fetch test was added (:203-212).\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_handler.py, which doesn't exist; a Glob for `**/test_video_handler*.py` found nothing. It was not read.\n2. `fixtures_path` was not supplied. Every fixture the test uses (`server`, `responses`) is defined in the test file, apart from pytest's own `tmp_path` and `monkeypatch`, so no conftest was needed. The schema helpers `ensure_whitelist_schema` and `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py were not read.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No shape.md entry covers this: stub question, previous behaviour. Location: tests/tmp/test_10_video_metadata_completeness_phase3.py:211-212\n   `assert tuple(server.db.execute(\"SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'\").fetchone()) == (\"newslug\", \"New Chan\", 3)  # C2`\n   `test_failed_channel_fetch_keeps_stored_followers` passes against video.py as it stands. The current handler already falls back to `row[\"channel_followers_count\"]` when the channel-detail fetch fails. That fallback is correct for this case. A wrong implementation that wrote `None` or dropped the fallback would still fail here, so this is not a stub-pass. But this test will not be red in the observed run, and it does not gate the phase's change.\n\nPREDICTED FAILURE\nAgainst the code as it stands:\n- test_fetch_failure_leaves_db_untouched:\n  - [urlerror] and [status-404] fail at line 150 (`_snapshot(server.db) == before`). `dynamic` is a non-empty dict, so the handler writes anyway: it advances `last_checked_at` and `popularity` and sets `instances.last_error*` to NULL.\n  - [not-json], [bad-utf8] and [json-list] error at line 145. `fetch_instance_json` does not catch `JSONDecodeError` or `UnicodeDecodeError`, and a JSON list raises `AttributeError` on `detail.get`.\n- test_success_refreshes_row_and_response fails at line 168. The row keeps `language='fr'`, `duration=10` and the old `thumbnail_url`.\n- Both test_partial_payload_keeps_tags_and_category cases fail at line 199. The response has no `duration` or `thumbnailUrl` key, so each reads as \"MISSING\".\n- test_empty_tag_list_propagates fails at line 221. `to_tags_json([])` returns None, so `tags_json` stays `'[\"old\"]'`.\n- test_object_body_counts_as_success:\n  - [object] fails at line 234 because `duration` stays 10.\n  - [empty-object] fails at line 236 because `duration` is \"MISSING\" in the reply.\n- test_second_request_reflects_source_change fails at line 248 because `tags` is \"MISSING\" in both responses.\n- test_failed_channel_fetch_keeps_stored_followers passes (see Recommendation 1).\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which does not resolve (FileNotFoundError). Its edits were not read.\n2. `fixtures_path` was not supplied. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/. Every fixture the test uses (`server`, `responses`) is defined in the test file itself, so nothing was left unresolved.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (37 clauses: 11 must_prove, 20 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\" | :150 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :148 shows the fetch was attempted | CARRIED |\n| C1b | must_prove | \"a malformed detail body\" leaves the same values unchanged | :150 (404, not-json, bad-utf8, json-list params :139) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |\n| C1c | must_prove | \"the response answers the DB values\": the metadata fields | :151, :152 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |\n| C1d | must_prove | \"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3) | :151 | `STORED_ANSWER` (:46) now holds `\"likes\": 1, \"dislikes\": 0, ... \"subscribersCount\": 3`, so the test fails if the failure path answers any other value for these three | CARRIED |\n| C2a | must_prove | \"writes the source value for each field present\": the videos row | :164, :166, :168 | any source field dropped, left at the seed or mapped to the wrong column. Every column is compared against `{**before, ...}` | CARRIED |\n| C2b | must_prove | \"writes the source value for each field present\": the channels row | :169 | slug, display name or followers not written from the source | CARRIED |\n| C2c | must_prove | \"the DB value for each field absent\": the videos row | :196 (absent and null-or-blank params :180-182) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |\n| C2d | must_prove | \"the DB value for each field absent\": the channels row | :197, :211 | an absent `channel` rewriting the channels row (:197), or a failed channel-detail fetch writing NULL over the stored follower count of 3 (:211) | CARRIED |\n| C2e | must_prove | \"the response answers the same merged values\": present fields | :171, :173, :174 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |\n| C2f | must_prove | response answers the merged values: absent metadata fields | :199, :200 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |\n| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | :199 | `expected = {**STORED_ANSWER, \"views\": 77}` (:198) now includes 1, 0 and 3, so the test fails if the response disagrees with the row (:196) on these fields | CARRIED |\n| D1 | docstring | \"writes the stored video only when the detail fetch returns a JSON object\" | :150, :234 | writing on a non-object body, or not writing on an object body | CARRIED |\n| D2 | docstring | \"on success stores and answers one source-over-DB value set\" | :168, :173 | the row and the response disagreeing on present fields | CARRIED |\n| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :139 params, :150 | any listed kind treated as success | CARRIED |\n| D4 | docstring | \"leaves the whole videos row, every channels row and instances.last_error* as they were\" | :150 | a partial write on failure | CARRIED |\n| D5 | docstring | \"answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count\" | :130, :151, :152 | a non-200 reply, or any named field answered with something other than the stored value | CARRIED |\n| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :164, :168, :169 | any named field not written, or a relative thumbnail stored | CARRIED |\n| D7 | docstring | \"moves last_checked_at forward\" | :166 | `last_checked_at` left unchanged | CARRIED |\n| D8 | docstring | \"clears instances.last_error*\" | :170 | the seeded error left in place | CARRIED |\n| D9 | docstring | \"leaves every other column as seeded\" | :168 | a write to a column outside the mapping | CARRIED |\n| D10 | docstring | \"keeps the 18 original response keys\" | :171 | an original key dropped | CARRIED |\n| D11 | docstring | \"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\" | :173, :174 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |\n| D12 | docstring | omitted, null, blank or null-language-id field \"keeps the stored value in the row\" | :196 | overwriting with NULL or blank | CARRIED |\n| D13a | docstring | \"... and in the response\": the fields named in STORED_ANSWER | :199, :200 | the response answering blanks for those fields | CARRIED |\n| D13b | docstring | \"... and in the response\": omitted likes and dislikes | :199 | the response answering anything other than the stored 1 and 0. Both are now in `STORED_ANSWER` | CARRIED |\n| D14 | docstring | \"`tags: []` stores \"[]\" and answers `[]`\" | :221, :222 | an empty list treated as absent, so the old tags are kept | CARRIED |\n| D15 | docstring | \"A JSON object body, `{}` included, counts as a success\" | :234, :235, :236 | `{}` treated as a failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |\n| D16 | docstring | \"A source change between two requests is in the second response and in the row\" | :248, :250 | a cached value, or one written only on the first fetch | CARRIED |\n| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :61-62, :76, :111 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:104) | CARRIED |\n| N1 | name | \"fetch failure leaves db untouched\" | :150 | a write on failure | CARRIED |\n| N2 | name | \"success refreshes row and response\" | :168, :173 | a stale row or response after success | CARRIED |\n| N3 | name | \"partial payload keeps tags and category\" | :196 | tags_json or category overwritten (both are inside `before`) | CARRIED |\n| N4 | name | \"empty tag list propagates\" | :221, :222 | `[]` ignored | CARRIED |\n| N5 | name | \"object body counts as success\" | :234 | `{}` or another object body not written | CARRIED |\n| N6 | name | \"second request reflects source change\" | :248, :250 | the first fetch's values persisting | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase3.py:6, :212\n   New docstring sentence, not in the ledger: \"A failed channel-detail fetch writes the source channel slug and display name and keeps the stored follower count, in the channels row and in the response.\"\n   - The row half is carried at :211.\n   - In the response, :212 asserts `channelName` and `subscribersCount` only. The slug reaches the response only through `channelUrl`, and nothing asserts `channelUrl`.\n   - So the test still passes if the response builds `channelUrl` from the stored `oldslug` instead of the source `newslug`. The \"slug ... in the response\" part of this sentence is uncarried.\n   - The same gap is in the full-payload test. :173 does not assert `channelUrl` either, even though the channel slug is a present field under C2e.\n   - To fix this, assert `channelUrl` or narrow the sentence.\n2. Clauses added since the ledger that are carried, for the record:\n   - Docstring :5, \"and leaves the channels row as it was\", is carried at :197.\n   - The new test name `test_failed_channel_fetch_keeps_stored_followers` is carried at :211 and :212.\n   - D5's sentence was widened to add likes, dislikes and subscriber count, not narrowed. It is carried at :151.\n3. The round-one UNCARRIED rows C1d, C2d, C2g and D13b were fixed by new assertions, not by narrowing the prose:\n   - `STORED_ANSWER` was extended (:46).\n   - A channels-row check was added at :197.\n   - A new failed-channel-fetch test was added (:203-212).\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_handler.py, which doesn't exist; a Glob for `**/test_video_handler*.py` found nothing. It was not read.\n2. `fixtures_path` was not supplied. Every fixture the test uses (`server`, `responses`) is defined in the test file, apart from pytest's own `tmp_path` and `monkeypatch`, so no conftest was needed. The schema helpers `ensure_whitelist_schema` and `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py were not read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a caught network error ... leaves every videos, channels and instances.last_error* value unchanged\"",
            "assertion": ":150",
            "excludes": "a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :148 shows the fetch was attempted",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"a malformed detail body\" leaves the same values unchanged",
            "assertion": ":150 (404, not-json, bad-utf8, json-list params :139)",
            "excludes": "a non-200, non-JSON, non-UTF-8 or list body being treated as success and written",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"the response answers the DB values\": the metadata fields",
            "assertion": ":151, :152",
            "excludes": "the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"the response answers the DB values\": likes, dislikes, subscribersCount (seeded 1, 0, 3)",
            "assertion": ":151",
            "excludes": "`STORED_ANSWER` (:46) now holds `\"likes\": 1, \"dislikes\": 0, ... \"subscribersCount\": 3`, so the test fails if the failure path answers any other value for these three",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"writes the source value for each field present\": the videos row",
            "assertion": ":164, :166, :168",
            "excludes": "any source field dropped, left at the seed or mapped to the wrong column. Every column is compared against `{**before, ...}`",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"writes the source value for each field present\": the channels row",
            "assertion": ":169",
            "excludes": "slug, display name or followers not written from the source",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"the DB value for each field absent\": the videos row",
            "assertion": ":196 (absent and null-or-blank params :180-182)",
            "excludes": "NULL or blank written over a stored value for an omitted, null or blank field",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"the DB value for each field absent\": the channels row",
            "assertion": ":197, :211",
            "excludes": "an absent `channel` rewriting the channels row (:197), or a failed channel-detail fetch writing NULL over the stored follower count of 3 (:211)",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "\"the response answers the same merged values\": present fields",
            "assertion": ":171, :173, :174",
            "excludes": "the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "response answers the merged values: absent metadata fields",
            "assertion": ":199, :200",
            "excludes": "the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw",
            "status": "CARRIED"
          },
          {
            "id": "C2g",
            "source": "must_prove",
            "clause": "response answers the merged values: absent likes, dislikes, subscribersCount",
            "assertion": ":199",
            "excludes": "`expected = {**STORED_ANSWER, \"views\": 77}` (:198) now includes 1, 0 and 3, so the test fails if the response disagrees with the row (:196) on these fields",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"writes the stored video only when the detail fetch returns a JSON object\"",
            "assertion": ":150, :234",
            "excludes": "writing on a non-object body, or not writing on an object body",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"on success stores and answers one source-over-DB value set\"",
            "assertion": ":168, :173",
            "excludes": "the row and the response disagreeing on present fields",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list",
            "assertion": ":139 params, :150",
            "excludes": "any listed kind treated as success",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"leaves the whole videos row, every channels row and instances.last_error* as they were\"",
            "assertion": ":150",
            "excludes": "a partial write on failure",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count\"",
            "assertion": ":130, :151, :152",
            "excludes": "a non-200 reply, or any named field answered with something other than the stored value",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "full payload writes title ... absolute thumbnail URL and the channel",
            "assertion": ":164, :168, :169",
            "excludes": "any named field not written, or a relative thumbnail stored",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"moves last_checked_at forward\"",
            "assertion": ":166",
            "excludes": "`last_checked_at` left unchanged",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"clears instances.last_error*\"",
            "assertion": ":170",
            "excludes": "the seeded error left in place",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"leaves every other column as seeded\"",
            "assertion": ":168",
            "excludes": "a write to a column outside the mapping",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"keeps the 18 original response keys\"",
            "assertion": ":171",
            "excludes": "an original key dropped",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"answers the same values (category and language as labels, tags as a list, nsfw as a bool)\"",
            "assertion": ":173, :174",
            "excludes": "raw codes, a JSON string for tags, or 1/0 for nsfw",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "omitted, null, blank or null-language-id field \"keeps the stored value in the row\"",
            "assertion": ":196",
            "excludes": "overwriting with NULL or blank",
            "status": "CARRIED"
          },
          {
            "id": "D13a",
            "source": "docstring",
            "clause": "\"... and in the response\": the fields named in STORED_ANSWER",
            "assertion": ":199, :200",
            "excludes": "the response answering blanks for those fields",
            "status": "CARRIED"
          },
          {
            "id": "D13b",
            "source": "docstring",
            "clause": "\"... and in the response\": omitted likes and dislikes",
            "assertion": ":199",
            "excludes": "the response answering anything other than the stored 1 and 0. Both are now in `STORED_ANSWER`",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"`tags: []` stores \"[]\" and answers `[]`\"",
            "assertion": ":221, :222",
            "excludes": "an empty list treated as absent, so the old tags are kept",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"A JSON object body, `{}` included, counts as a success\"",
            "assertion": ":234, :235, :236",
            "excludes": "`{}` treated as a failure: no `last_checked_at` bump, and the error is not cleared",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"A source change between two requests is in the second response and in the row\"",
            "assertion": ":248, :250",
            "excludes": "a cached value, or one written only on the first fetch",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted",
            "assertion": ":61-62, :76, :111 (setup, not assertions)",
            "excludes": "a real network call. Unlisted paths raise `URLError` (:104)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"fetch failure leaves db untouched\"",
            "assertion": ":150",
            "excludes": "a write on failure",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"success refreshes row and response\"",
            "assertion": ":168, :173",
            "excludes": "a stale row or response after success",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"partial payload keeps tags and category\"",
            "assertion": ":196",
            "excludes": "tags_json or category overwritten (both are inside `before`)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"empty tag list propagates\"",
            "assertion": ":221, :222",
            "excludes": "`[]` ignored",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"object body counts as success\"",
            "assertion": ":234",
            "excludes": "`{}` or another object body not written",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"second request reflects source change\"",
            "assertion": ":248, :250",
            "excludes": "the first fetch's values persisting",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_10_video_metadata_completeness_phase4.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three tests should pass their controls in `_page` (lines 105-109) and then fail on the first taxonomy assertion.\n- Line 116 fails as `None is False`. `index.ts` never calls `getElementById(\"video-category\")`, so the runner's `report(\"video-category\")` (runner line 77) gives `hidden: null`.\n- Line 126 fails as `None is True`, for the same reason.\n- Line 134 fails as `None is False`, for the same reason.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_video_taxonomy.py (NEW). That path does not exist, so it was not read.\n2. `code_under_test` lists client/frontend/dist (rebuilt). The test bundles `src/pages/video-page/index.ts` with esbuild and never loads `dist` (lines 88-94), so `dist` was not read.\n3. Whether esbuild at `node_modules/.bin/esbuild` and `node` are present was not checked. The prediction assumes both are, and that the `_page` controls pass.\n```\n\nBasis for the verdict (not part of the gate record):\n- **Anti-pattern pass:** the test fails none of the eight `<how_to_spot>` checks.\n  - It never reads a `.md` file and never greps a section or source name.\n  - The expected values are written into the test as literals, not re-derived from the code.\n  - C2's hidden-state assertions (lines 126-127) sit next to the positive `\"No tags\"` assertion (line 128) and the `_page` controls (lines 108-109), and `initially_hidden=[]` means the page must set `hidden` itself.\n  - The input values are not echoed back to the test untouched: they pass through the page's fetch\u2192render path, and deleting the page's taxonomy code turns every test red.\n  - The category is checked at two values (\"Science & Technology\" and \"Music\"). Every item starts in the opposite visibility to the one expected, and each `getElementById` stub returns a fresh empty element, so no shipped default can satisfy an assertion.\n- **Ladder pass:** the test is at rung 1. It imports the real page module into a stubbed DOM and asserts on the element state it leaves behind. The node subprocess is only there to run TypeScript, not a downshift, so no downshift comment is needed.\n- **Stub question:** a stub page fails.\n  - An unchanged page fails at lines 116, 126 and 134.\n  - Hard-coding \"No tags\" fails line 120.\n  - Hard-coding a category fails line 117 or line 135.\n  - Always showing both items fails line 126. Always hiding them fails line 116.\n  - Writing tags through `innerHTML` fails line 120, because the runner keeps markup opaque (runner line 41).",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 9 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with a category, \"the block shows the category value\" | :116, :117 | the item left hidden (it starts hidden at :114, so the page has to unhide it); a missing or wrong value | CARRIED |\n| C1b | must_prove | with a language, \"the block shows ... the language value\" | :118, :119 | the item left hidden (it starts hidden); a missing or wrong value | CARRIED |\n| C1c | must_prove | \"one text chip per tag\" | :120 | tags joined into one chip, a dropped tag, a reordered list, a child without `tag-chip`, a chip filled through innerHTML (the stub makes that text read as \"\") | CARRIED |\n| C2a | must_prove | with an empty category, \"the category ... item [is] hidden\" | :126 | a page that never sets visibility (it starts visible, `initially_hidden=[]` at :124) | CARRIED |\n| C2b | must_prove | with an empty language, \"the ... language item [is] hidden\" | :127 | the same, for the language item | CARRIED |\n| C2c | must_prove | an empty tag list \"reads 'No tags'\" | :128 | an empty list, leftover chips, other text, markup written through innerHTML | CARRIED |\n| D1 | docstring | \"run in node with the real page module\" | :109 | a harness that never ran index.ts: the title from the body only appears if the real loadVideo ran | CARRIED |\n| D2 | docstring | \"shows the category, language and tags from `/api/video` as text\" | :108, :117, :119, :120 | values taken from somewhere other than `/api/video` (only that path returns the body); values not written as text | CARRIED |\n| D3 | docstring | two tags give \"one `tag-chip` per tag, in order, whose text is the tag\" | :120 | the wrong order, a missing class, the wrong text | CARRIED |\n| D4 | docstring | \"category and language items are shown with the body's values\" | :116\u2013:119 | items left hidden; the wrong values | CARRIED |\n| D5 | docstring | empty body: \"category and language items are hidden\" | :126, :127 | visibility never set | CARRIED |\n| D6 | docstring | \"the tag list's only child reads 'No tags'\" | :128 | an extra child next to the placeholder (the whole list is compared, so length is checked) | CARRIED |\n| D7 | docstring | category, empty language, one tag: \"only the language item is hidden\" | :134, :136 | hiding both when one field is empty; hiding neither | CARRIED |\n| D8 | docstring | \"and the tag list holds one chip\" | :137 | the \"No tags\" text or an extra chip | CARRIED |\n| D9 | docstring | \"Each taxonomy item starts in the opposite visibility to the one expected\" | :114, :124, :132 (setup) \u2192 :116/:118, :126/:127, :134/:136 | a page that never changes `hidden` passing by default. Checked against each case's `initially_hidden` | CARRIED |\n| N1 | name | test 1: \"shows both values\" | :117, :119 | a missing or wrong value | CARRIED |\n| N2 | name | test 1: \"one text chip per tag\" | :120 | as in C1c | CARRIED |\n| N3 | name | test 2: \"hides both items\" | :126, :127 | visibility never set | CARRIED |\n| N4 | name | test 2: \"reads no tags\" | :128 | as in C2c | CARRIED |\n| N5 | name | test 3: \"an empty language alone hides only the language item\" | :134, :136 | hiding the category too, or not hiding the language item | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. surfaces (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:63\n   `getElementById: (id) => { if (!byId.has(id)) byId.set(id, element(\"div\", ...)); ... }`\n   The fake `document` creates an element for any id the module asks for. So none of the asserts from :116 to :137 depend on `video-page.html`, which the phase edited and lists in `code_under_test`. The test would still pass if the markup lacked `video-category`, `video-category-value`, `video-language`, `video-language-value` or `video-tags`. The C1 and C2 rows are CARRIED for the module's behaviour. \"The block shows\" is only proved if the HTML actually has those elements, and this test does not check that. `<surfaces>` says shims belong on the far side of the boundary, and the HTML is changed code, not a severed layer. Whether this matters depends on the seam the phase's `<checkpoint>` names, and that seam was not supplied (see NOT ASSESSED).\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:124\n   The only \"absent\" input tested is the empty string or empty list. These cases never run: `category`/`language`/`tags` missing from the body, `null` values, a non-array `tags`, a non-string tag, a whitespace-only category, and an empty category with a language present (the mirror of test 3 at :132).\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:71\n   The fake `fetch` always returns 200 for `/api/video`. Nothing tests what the taxonomy block shows when that call fails or returns non-JSON, which is when the page falls back to the instance metadata (`fetchVideoMetadataFromInstance`, index.ts:560).\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/src/pages/video-page/index.ts, client/frontend/video-page.html and client/frontend/src/video.css as EDITED. As read, none of them contains `video-category`, `video-language`, `video-tags`, `tag-chip`, \"No tags\", or any read of `category`/`language`/`tags` from the body; a Grep for those words across client/frontend (excluding node_modules) matched nothing. I could not see which inputs the code accepts, so I judged bounds and the failure path from the test and `must_prove` alone.\n2. tests/active/test_frontend_video_taxonomy.py is listed in `code_under_test` as NEW but does not exist, so I could not read it.\n3. client/frontend/dist was not read. The test builds its own bundle from src (:89), so dist is not part of what the test exercises.\n4. The seam named by the phase's `<checkpoint>` was not supplied. Without it I could not settle whether the fake `document` at :61\u2013:66 is a legitimate shim for this checkpoint (Recommendation 1).",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three tests should pass their controls in `_page` (lines 105-109) and then fail on the first taxonomy assertion.\n- Line 116 fails as `None is False`. `index.ts` never calls `getElementById(\"video-category\")`, so the runner's `report(\"video-category\")` (runner line 77) gives `hidden: null`.\n- Line 126 fails as `None is True`, for the same reason.\n- Line 134 fails as `None is False`, for the same reason.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_video_taxonomy.py (NEW). That path does not exist, so it was not read.\n2. `code_under_test` lists client/frontend/dist (rebuilt). The test bundles `src/pages/video-page/index.ts` with esbuild and never loads `dist` (lines 88-94), so `dist` was not read.\n3. Whether esbuild at `node_modules/.bin/esbuild` and `node` are present was not checked. The prediction assumes both are, and that the `_page` controls pass.\n```\n\nBasis for the verdict (not part of the gate record):\n- **Anti-pattern pass:** the test fails none of the eight `<how_to_spot>` checks.\n  - It never reads a `.md` file and never greps a section or source name.\n  - The expected values are written into the test as literals, not re-derived from the code.\n  - C2's hidden-state assertions (lines 126-127) sit next to the positive `\"No tags\"` assertion (line 128) and the `_page` controls (lines 108-109), and `initially_hidden=[]` means the page must set `hidden` itself.\n  - The input values are not echoed back to the test untouched: they pass through the page's fetch\u2192render path, and deleting the page's taxonomy code turns every test red.\n  - The category is checked at two values (\"Science & Technology\" and \"Music\"). Every item starts in the opposite visibility to the one expected, and each `getElementById` stub returns a fresh empty element, so no shipped default can satisfy an assertion.\n- **Ladder pass:** the test is at rung 1. It imports the real page module into a stubbed DOM and asserts on the element state it leaves behind. The node subprocess is only there to run TypeScript, not a downshift, so no downshift comment is needed.\n- **Stub question:** a stub page fails.\n  - An unchanged page fails at lines 116, 126 and 134.\n  - Hard-coding \"No tags\" fails line 120.\n  - Hard-coding a category fails line 117 or line 135.\n  - Always showing both items fails line 126. Always hiding them fails line 116.\n  - Writing tags through `innerHTML` fails line 120, because the runner keeps markup opaque (runner line 41).\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 9 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with a category, \"the block shows the category value\" | :116, :117 | the item left hidden (it starts hidden at :114, so the page has to unhide it); a missing or wrong value | CARRIED |\n| C1b | must_prove | with a language, \"the block shows ... the language value\" | :118, :119 | the item left hidden (it starts hidden); a missing or wrong value | CARRIED |\n| C1c | must_prove | \"one text chip per tag\" | :120 | tags joined into one chip, a dropped tag, a reordered list, a child without `tag-chip`, a chip filled through innerHTML (the stub makes that text read as \"\") | CARRIED |\n| C2a | must_prove | with an empty category, \"the category ... item [is] hidden\" | :126 | a page that never sets visibility (it starts visible, `initially_hidden=[]` at :124) | CARRIED |\n| C2b | must_prove | with an empty language, \"the ... language item [is] hidden\" | :127 | the same, for the language item | CARRIED |\n| C2c | must_prove | an empty tag list \"reads 'No tags'\" | :128 | an empty list, leftover chips, other text, markup written through innerHTML | CARRIED |\n| D1 | docstring | \"run in node with the real page module\" | :109 | a harness that never ran index.ts: the title from the body only appears if the real loadVideo ran | CARRIED |\n| D2 | docstring | \"shows the category, language and tags from `/api/video` as text\" | :108, :117, :119, :120 | values taken from somewhere other than `/api/video` (only that path returns the body); values not written as text | CARRIED |\n| D3 | docstring | two tags give \"one `tag-chip` per tag, in order, whose text is the tag\" | :120 | the wrong order, a missing class, the wrong text | CARRIED |\n| D4 | docstring | \"category and language items are shown with the body's values\" | :116\u2013:119 | items left hidden; the wrong values | CARRIED |\n| D5 | docstring | empty body: \"category and language items are hidden\" | :126, :127 | visibility never set | CARRIED |\n| D6 | docstring | \"the tag list's only child reads 'No tags'\" | :128 | an extra child next to the placeholder (the whole list is compared, so length is checked) | CARRIED |\n| D7 | docstring | category, empty language, one tag: \"only the language item is hidden\" | :134, :136 | hiding both when one field is empty; hiding neither | CARRIED |\n| D8 | docstring | \"and the tag list holds one chip\" | :137 | the \"No tags\" text or an extra chip | CARRIED |\n| D9 | docstring | \"Each taxonomy item starts in the opposite visibility to the one expected\" | :114, :124, :132 (setup) \u2192 :116/:118, :126/:127, :134/:136 | a page that never changes `hidden` passing by default. Checked against each case's `initially_hidden` | CARRIED |\n| N1 | name | test 1: \"shows both values\" | :117, :119 | a missing or wrong value | CARRIED |\n| N2 | name | test 1: \"one text chip per tag\" | :120 | as in C1c | CARRIED |\n| N3 | name | test 2: \"hides both items\" | :126, :127 | visibility never set | CARRIED |\n| N4 | name | test 2: \"reads no tags\" | :128 | as in C2c | CARRIED |\n| N5 | name | test 3: \"an empty language alone hides only the language item\" | :134, :136 | hiding the category too, or not hiding the language item | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. surfaces (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:63\n   `getElementById: (id) => { if (!byId.has(id)) byId.set(id, element(\"div\", ...)); ... }`\n   The fake `document` creates an element for any id the module asks for. So none of the asserts from :116 to :137 depend on `video-page.html`, which the phase edited and lists in `code_under_test`. The test would still pass if the markup lacked `video-category`, `video-category-value`, `video-language`, `video-language-value` or `video-tags`. The C1 and C2 rows are CARRIED for the module's behaviour. \"The block shows\" is only proved if the HTML actually has those elements, and this test does not check that. `<surfaces>` says shims belong on the far side of the boundary, and the HTML is changed code, not a severed layer. Whether this matters depends on the seam the phase's `<checkpoint>` names, and that seam was not supplied (see NOT ASSESSED).\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:124\n   The only \"absent\" input tested is the empty string or empty list. These cases never run: `category`/`language`/`tags` missing from the body, `null` values, a non-array `tags`, a non-string tag, a whitespace-only category, and an empty category with a language present (the mirror of test 3 at :132).\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_10_video_metadata_completeness_phase4.py:71\n   The fake `fetch` always returns 200 for `/api/video`. Nothing tests what the taxonomy block shows when that call fails or returns non-JSON, which is when the page falls back to the instance metadata (`fetchVideoMetadataFromInstance`, index.ts:560).\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/src/pages/video-page/index.ts, client/frontend/video-page.html and client/frontend/src/video.css as EDITED. As read, none of them contains `video-category`, `video-language`, `video-tags`, `tag-chip`, \"No tags\", or any read of `category`/`language`/`tags` from the body; a Grep for those words across client/frontend (excluding node_modules) matched nothing. I could not see which inputs the code accepts, so I judged bounds and the failure path from the test and `must_prove` alone.\n2. tests/active/test_frontend_video_taxonomy.py is listed in `code_under_test` as NEW but does not exist, so I could not read it.\n3. client/frontend/dist was not read. The test builds its own bundle from src (:89), so dist is not part of what the test exercises.\n4. The seam named by the phase's `<checkpoint>` was not supplied. Without it I could not settle whether the fake `document` at :61\u2013:66 is a legitimate shim for this checkpoint (Recommendation 1).",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "with a category, \"the block shows the category value\"",
            "assertion": ":116, :117",
            "excludes": "the item left hidden (it starts hidden at :114, so the page has to unhide it); a missing or wrong value",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "with a language, \"the block shows ... the language value\"",
            "assertion": ":118, :119",
            "excludes": "the item left hidden (it starts hidden); a missing or wrong value",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"one text chip per tag\"",
            "assertion": ":120",
            "excludes": "tags joined into one chip, a dropped tag, a reordered list, a child without `tag-chip`, a chip filled through innerHTML (the stub makes that text read as \"\")",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "with an empty category, \"the category ... item [is] hidden\"",
            "assertion": ":126",
            "excludes": "a page that never sets visibility (it starts visible, `initially_hidden=[]` at :124)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "with an empty language, \"the ... language item [is] hidden\"",
            "assertion": ":127",
            "excludes": "the same, for the language item",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "an empty tag list \"reads 'No tags'\"",
            "assertion": ":128",
            "excludes": "an empty list, leftover chips, other text, markup written through innerHTML",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"run in node with the real page module\"",
            "assertion": ":109",
            "excludes": "a harness that never ran index.ts: the title from the body only appears if the real loadVideo ran",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"shows the category, language and tags from `/api/video` as text\"",
            "assertion": ":108, :117, :119, :120",
            "excludes": "values taken from somewhere other than `/api/video` (only that path returns the body); values not written as text",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "two tags give \"one `tag-chip` per tag, in order, whose text is the tag\"",
            "assertion": ":120",
            "excludes": "the wrong order, a missing class, the wrong text",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"category and language items are shown with the body's values\"",
            "assertion": ":116\u2013:119",
            "excludes": "items left hidden; the wrong values",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "empty body: \"category and language items are hidden\"",
            "assertion": ":126, :127",
            "excludes": "visibility never set",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the tag list's only child reads 'No tags'\"",
            "assertion": ":128",
            "excludes": "an extra child next to the placeholder (the whole list is compared, so length is checked)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "category, empty language, one tag: \"only the language item is hidden\"",
            "assertion": ":134, :136",
            "excludes": "hiding both when one field is empty; hiding neither",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"and the tag list holds one chip\"",
            "assertion": ":137",
            "excludes": "the \"No tags\" text or an extra chip",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Each taxonomy item starts in the opposite visibility to the one expected\"",
            "assertion": ":114, :124, :132 (setup) \u2192 :116/:118, :126/:127, :134/:136",
            "excludes": "a page that never changes `hidden` passing by default. Checked against each case's `initially_hidden`",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"shows both values\"",
            "assertion": ":117, :119",
            "excludes": "a missing or wrong value",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"one text chip per tag\"",
            "assertion": ":120",
            "excludes": "as in C1c",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"hides both items\"",
            "assertion": ":126, :127",
            "excludes": "visibility never set",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"reads no tags\"",
            "assertion": ":128",
            "excludes": "as in C2c",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 3: \"an empty language alone hides only the language item\"",
            "assertion": ":134, :136",
            "excludes": "hiding the category too, or not hiding the language item",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone - I read all four phases' production code (schema.sql, db.ts, videos-worker.ts, both dist files, whitelist_migrations.py, sync-whitelist.py, peertube_labels.py, handlers/video.py, video-page.html, index.ts, video.css) and found nothing in this build's changes worth consolidating without changing behaviour, so I edited no file.\n</refactors>\n\n<left_out>\nMerging `migrateVideosLanguage` into `migrateVideos` (db.ts), and `migrate_videos_language` into `migrate_videos_schema` (whitelist_migrations.py): left out because both paths are needed. The rebuild only fires when the error columns are missing, so a table that already has them but lacks `language` can only get it from the ALTER. Folding them together would change which DBs get migrated.\nReading `extract_language`/`extractLanguage` and `category_label`/`language_label` from one shared place: left out because they live on opposite sides of the TS/Python boundary, and each already matches the style of its file.\nPulling the tag-chip rendering in `loadVideo` (index.ts) into its own helper next to `renderTaxonomyItem`: left out because it would be cosmetic only, with one call site and no second user.\nThe pre-existing duplication in videos-worker.ts (`groupByInstance`/`groupByInstanceTags`/`groupByInstanceComments`, `processTagInstance`/`processCommentsInstance`) and the `DEPRECATED_*` migration scaffolding in db.ts: left out because this build did not write them, and changing them would grow the build past what was approved.\nengine/crawler/dist/db.js and dist/videos-worker.js: these are still hand-edited rather than tsc output, and I can't run a shell to rebuild them. The operator should run `cd engine/crawler && npm install && npm run build` and review the dist diff before commit.\nclient/frontend/dist: still not rebuilt (phase 4 had the same limit). The operator should run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before merge.\nThe probes this build left in tests/tmp: probe_10_dist_language.py (emptied), probe_10_phase4_impl.py, probe_10_phase4_taxonomy.py, probe_10_phase3_channels.py, probe_10_phase3_refresh.py, probe_10_phase2_shape.py, probe_10_phase2_labels.py, probe_10_crawl.py and probe_10_language.py. I have no delete tool, so the operator needs to remove them.\nThe step's \"What the pass is measured against\" section reached me as an unfilled `{rat_tail_rules}` placeholder. I measured against the role's rules instead: the build's only deliberate simplification, the stock label lists in peertube_labels.py, already has a `rat-tail:` comment naming the ceiling and the upgrade path.\n</left_out>\n\n<needs_fresh_red>\nnone - mapping category, language and tags in the video page's PeerTube-instance fallback (`fetchVideoMetadataFromInstance`) would be new behaviour, but phase 4 left it out of scope on purpose, so it belongs on the roadmap if wanted, not in this pass.\n</needs_fresh_red>\n\n<observation>\nFrom reading the code (nothing was run, and no file changed): the landed code needs no refactor, and the unbuilt dist output plus the leftover tests/tmp probes are the only loose ends, both for the operator.\n</observation>"
}
```
dev-flow:state -->

## 2026-09-27 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/10",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 23 test groups (22 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

The video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) must show what the source PeerTube instance currently says about a video, including its tags, category and language. Every `/api/video` request (`engine/server/api/handlers/video.py`, `handle_video_request`) must bring the server DB copy of the video's mutable fields up to date, and that copy also feeds search FTS (`videos_fts` triggers) and embeddings (`build-video-embeddings.py` reads `tags_json`/`category`). A failed or unreachable instance must never change stored data.

### Baseline suite state

Pre-build suite exited 0 (variant: false). Resolved paths: active tests `tests/active`, working tests `tests/tmp`, plans `docs/project/plans`, archive `tests/archive`, delete_me `delete_me`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser/.worktrees/10`.

### Current state found in the tree (context for later steps)

- `fetch_instance_video_dynamic` already fetches `/api/v1/videos/{id}` plus `/api/v1/video-channels/{slug}`, normalises title/description/views/likes/dislikes/tags_json/category/nsfw, and the handler already UPDATEs `videos` (title, description, channel_name, views, likes, dislikes, popularity, tags_json, category, nsfw, last_checked_at), `channels`, and resets `instances.last_error/last_error_at/last_error_source`.
- Defect: `fetch_instance_video_dynamic` always returns a non-empty dict (keys with `None` values) even when `fetch_instance_json` returned `None`. So `if dynamic and ...` is always true, and on instance failure the handler still writes `videos` (with DB fallback values), bumps `last_checked_at`, writes `channels`, and clears `instances.last_error`.
- Defect: `to_tags_json` returns `None` for an empty list, so a source that removed all tags never propagates. `extract_category` drops a category that has only an `id`.
- The `/api/video` response does not include tags, category, nsfw, language, duration or thumbnail.
- There is no `language` column in any schema (crawler `engine/crawler/schema.sql`, whitelist `engine/server/db/jobs/whitelist_migrations.py`, `engine/server/db/jobs/sync-whitelist.py`). `duration`, `thumbnail_url`, `nsfw`, `tags_json` and `category` exist in both.
- The crawler (`engine/crawler/src/videos-worker.ts` `extractCategory`) stores the category label, or `String(id)` when no label exists, so DB rows can hold numeric category strings such as "15".
- No active test covers `/api/video` today.

### R1 — Successful-refresh rule (a fix to current behaviour)

- A refresh is successful exactly when the video detail fetch `/api/v1/videos/{id}` returns a JSON object (dict).
- The existing fetch contract stays as it is: `urlopen(..., timeout=8)`, catching `HTTPError`, `URLError`, `TimeoutError`, and a non-200 status returning `None`. In addition, a body that is not valid JSON, or valid JSON that is not an object, is treated as failure (returns no data) instead of raising out of the handler.
- A failure of the secondary channel-detail fetch (`/api/v1/video-channels/{slug}`) does not make the refresh unsuccessful. The channel fields then fall back as they do today.
- On success: one transaction UPDATEs the `videos` row (fields per R2, plus `popularity` and `last_checked_at = now`), UPDATEs the `channels` row as today, and resets `instances.last_error`, `last_error_at` and `last_error_source` for the host. The existing `sqlite3.OperationalError` catch-and-log is kept.
- On failure: no UPDATE to `videos`, `channels` or `instances` runs at all. `last_checked_at` is unchanged, `instances.last_error` is unchanged, and the response is built field by field from the DB row.

### R2 — Field mapping rules (one write path)

There is a single UPDATE path in the handler. For each mutable field, a value present and valid in the source payload overwrites the DB value. A value that is absent, null or invalid keeps the DB value, both in the response and in what is written.

- `title`: source `name` (or `title`), a non-empty trimmed string; otherwise keep DB.
- `description`: source `description`, a non-empty trimmed string; otherwise keep DB. An empty string keeps DB (current `pick_text` behaviour, deliberately kept).
- `views`, `likes`, `dislikes`: int-like source values (existing aliases `viewsCount`/`views_count`, etc.); otherwise keep DB.
- `tags_json`: if source `tags` is a list, overwrite with the JSON array of its string elements. An empty list is stored as `"[]"` so removals propagate. If `tags` is absent or not a list, keep DB.
- `category`: source `category` object → its `label` (or `name`) if non-empty, else its `id` as a string. A plain string or number is stored as a string. Absent/null keeps DB.
- `language` (new column): source `language` object → its `id` (the PeerTube language code, e.g. `"en"`). A plain string is stored as is. Absent/null or a null id keeps DB.
- `nsfw`: source boolean/int-like → 0/1 (existing `to_nullable_bool`); absent/null keeps DB.
- `duration`: source `duration`, int-like seconds; otherwise keep DB.
- `thumbnail_url`: source `thumbnailUrl`, else `thumbnailPath`, resolved to an absolute `https://{host}...` URL (existing `resolve_asset_url`); otherwise keep DB.
- `popularity`: recomputed from the merged views/likes as today, written only on success.
- `last_checked_at`: set to now only on success.

A partial source response (for example, stats present but tags/category missing) must never wipe the stored tags or category.

### R3 — Language column (schema change across producers)

- Add `language TEXT` (nullable) to the `videos` table in `engine/crawler/schema.sql`. The crawler DB layer (`engine/crawler/src/db.ts`, including its videos insert/upsert and the `videos_new` rebuild) and `engine/crawler/src/videos-worker.ts` must extract and persist `language` from the PeerTube video payload using the same rule as R2 (the language id/code).
- Add `language` to the server whitelist `videos` schema through a new migration in `engine/server/db/jobs/whitelist_migrations.py` that is safe on existing databases (additive column). `engine/server/db/jobs/sync-whitelist.py` must create and copy the column.
- `fetch_video_row` selects `v.language`.
- Rebuild the committed crawler `dist/` JS if the repository keeps it in sync with `src/` (`engine/crawler/dist/db.js`, `videos-worker.js`).

### R4 — Category and language display labels

- A static, stdlib-only map in the server holds PeerTube's default video categories (ids 1–18 → labels, e.g. 1 Music, 2 Films, 3 Vehicles, 4 Art, 5 Sports, 6 Travels, 7 Gaming, 8 People, 9 Comedy, 10 Entertainment, 11 News & Politics, 12 How To, 13 Education, 14 Activism, 15 Science & Technology, 16 Animals, 17 Kids, 18 Food) and PeerTube's default language codes → labels.
- When `/api/video` builds its response, a stored category that is a digit-only string resolves through the map to its label. Any other stored value is shown as is. An unknown id is shown as the raw value. A stored language code resolves to its label; an unknown code is shown as the raw code.
- Named simplification: this map covers only PeerTube's defaults. Instances with plugin-added or renamed categories/languages display the raw id or code. Upgrade path: fetch and cache the instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`.

### R5 — `/api/video` response contract

All existing response keys are kept unchanged. New keys, each from the merged value (source on success, else DB):

- `tags`: a list of strings parsed from `tags_json` (empty list when null, empty, or unparseable).
- `category`: the display label per R4, or `""`.
- `language`: the display label per R4, or `""`.
- `nsfw`: boolean or `null`.
- `duration`: integer seconds or `null`.
- `thumbnailUrl`: string or `""`.

The Client backend proxy (`client/backend/server.py`, `/api/video` in `PROXY_READ_GET_ROUTES`) passes the body through, and must continue to do so with the new keys.

### R6 — Video page UI

- In the existing metadata area of `client/frontend/video-page.html` (near `video-meta-row` / `video-description`), add a compact metadata block that shows:
  - the category label (hidden when empty),
  - the language label (hidden when empty),
  - tags as chips, with the empty state "No tags" when the list is empty.
- `client/frontend/src/pages/video-page/index.ts`: extend `VideoMetadata` with `tags`, `category` and `language`. Fill them in `fetchVideoMetadataFromServer` from the new response keys, and in the instance-direct fallback `fetchVideoMetadataFromInstance` from the PeerTube payload (`tags` list, `category.label`, `language.label`). Render them in `loadVideo`. All values are HTML-escaped (existing `escapeHtml`) or set via `textContent`.
- Styling goes in `client/frontend/src/video.css`, compact and consistent with the existing metadata styles. Rebuild `client/frontend/dist` if the repository keeps it committed.

### R7 — Tests (active suite, `tests/active`)

A new test module for the `/api/video` handler. It uses a SQLite DB created from the production server (whitelist) `videos`/`channels`/`instances` schema, not a hand-picked column subset, and stubs the instance fetch (`fetch_instance_json`) with no network access. It covers:

- Success fixture: after one request, the DB row holds the source `title`, `description`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, `language`, `duration`, `thumbnail_url`, and a `last_checked_at` newer than before. `instances.last_error`, `last_error_at` and `last_error_source` are reset to NULL. The response carries the new keys per R5.
- Instance-fail fixtures: at least one each for a caught network error (e.g. `URLError`/`TimeoutError`, via the stub returning `None`) and a malformed/non-object body. Assert every `videos` column is unchanged (no overwrite, `last_checked_at` unchanged), the `channels` row is unchanged, `instances.last_error` is still set, and the response values equal the DB values.
- Partial-response regression: a source payload with stats but no `tags` and no `category` keeps the stored `tags_json` and `category`. A payload with `tags: []` stores `"[]"` and returns `tags: []`.
- Integration: a source metadata change (e.g. new title and tags) between two requests is reflected in the second `/api/video` response and in the DB.
- Label mapping: a stored digit-only category (e.g. `"15"`) is returned as its label ("Science & Technology"); an unknown id is returned raw; a language code is returned as its label.
- Crawler: `language` is persisted by the crawler videos path (extend `tests/active/test_videos_worker.py`, which already builds from `engine/crawler/schema.sql`).
- Whitelist migration: the new migration adds `language` to an existing DB without losing rows.

Manual validation (not automated): tags, category and language render on the video page, and the "No tags" empty state shows for a video without tags.

### Out of scope

- Fetching per-instance category/language lists (R4 upgrade path).
- Changing the refresh cadence or adding caching of `/api/video`.
- Displaying nsfw, duration or thumbnail on the video page (they are refreshed, stored and returned, but R6 renders only category, language and tags).

### conflicts

Request "keep the current fallback … DB update and instances.last_error reset run only on a successful refresh" vs engine/server/api/handlers/video.py: fetch_instance_video_dynamic always returns a non-empty dict, so `if dynamic and instance_domain and row.get("video_id")` is true on failure too and the handler currently writes videos/channels, bumps last_checked_at and clears instances.last_error after a failed fetch. This is a fix, not preservation (R1).
Request "refresh tags" and regression "do not wipe tags on partial responses" vs video.py to_tags_json: an empty source tag list becomes None and falls back to the DB, so tag removals never propagate. Resolved in R2 as absent → keep, empty list → "[]".
Request "optionally language" vs the schema: no language column exists in engine/crawler/schema.sql, whitelist_migrations.py or sync-whitelist.py. The operator chose to include it, which requires the schema/crawler/sync changes in R3.
Request "a numeric source category maps to a display label consistently" vs engine/crawler/src/videos-worker.ts extractCategory storing String(id) and video.py extract_category dropping id-only categories. Resolved by the static default-category map in R4 (operator choice), with the named ceiling for custom instance categories.
Request "keep … catching HTTPError/URLError/TimeoutError" vs fetch_instance_json: json.loads on a malformed body raises out of the handler (500). R1 widens failure to include malformed/non-object JSON, which goes beyond the three named exceptions.

## 2026-09-27 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

The work falls into four parts, each confined to the files the requirements name: the handler, the schema, the page and the tests. What follows was checked against `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, the crawler's `schema.sql`, `db.ts` and `videos-worker.ts`, the video page sources and `tests/active`.

**1. Handler: one success signal, one merge, one write (R1, R2, R5)** in `engine/server/api/handlers/video.py`.

- **`fetch_instance_json`** keeps its contract: `urlopen(..., timeout=8)`, the same three caught exceptions, and a non-200 status still returns `None`. Two cases are added, both logged at info like the network failures:
  - a body that fails to decode or parse (`ValueError`, which covers both `JSONDecodeError` and `UnicodeDecodeError`) returns `None`;
  - a parsed value that is not a `dict` returns `None`.
- **`fetch_instance_video_dynamic`** returns `None` when the detail fetch gives no dict. That is the single success signal R1 defines. The channel-detail fetch keeps its current fallback, so its failure never turns a refresh into a failure.
  - Presence is kept distinct from emptiness. `tags` is no longer coerced with `or []`, so a missing key and an empty list stay different.
  - `to_tags_json` returns `"[]"` for an empty list and `None` only when the value is not a list.
  - `extract_category` falls back to `str(id)` when the object has no label, and turns a number into a string.
  - A small `extract_language` returns the object's `id` (or a plain non-empty string). A null id returns `None`.
  - `duration` goes through `pick_number`. `thumbnail_url` goes through `resolve_asset_url(host, thumbnailUrl or thumbnailPath)`.
  - A `None` in the dynamic dict always means "keep the DB value".
- **`fetch_video_row`** also selects `v.language`, `v.duration` and `v.thumbnail_url`. The last two are needed so the fallback response can serve them from the DB.
- **`handle_video_request`** builds one merged set of values:
  - each field is the source value when it is present and valid, otherwise the DB value, using the existing `pick_text`/`pick_number`/None-check rules;
  - that one set feeds both the response and the UPDATE, so the two can never disagree;
  - when `dynamic is None` (fetch failed, or no host), the merged values are just the DB row and the whole write block is skipped. No `videos`, `channels` or `instances` statement runs;
  - on success the existing single transaction runs with the SET list extended by `language`, `duration` and `thumbnail_url`, plus `popularity` and `last_checked_at`. The `channels` update and the `instances.last_error*` reset stay as they are, and so does the `OperationalError` catch.
- **Response.** Every existing key is kept, plus:
  - `tags`: parsed from the merged `tags_json`, keeping string elements only, and `[]` on null, empty or unparseable;
  - `category` and `language`: display labels (see part 2), or `""`;
  - `nsfw`: a bool or `null`;
  - `duration`: an int or `null`;
  - `thumbnailUrl`: a string or `""`.
- **Client proxy.** `client/backend/server.py` needs no change: `/api/video` is in `PROXY_READ_GET_ROUTES`, which passes the body through.

**2. Display labels (R4).** A new stdlib-only module, `engine/server/data/peertube_labels.py`, holds two dicts:

- PeerTube's default categories: `"1"`–`"18"` mapped to labels, exactly as listed in R4.
- PeerTube's default language codes mapped to labels, copied once from a stock instance's `/api/v1/videos/languages` output and committed as a literal dict.

It has two tiny lookup functions:
- category: a digit-only string resolves through the map; any other value, or an unknown id, is returned as it is;
- language: a known code resolves to its label; an unknown code is returned raw.

The handler uses them only when it builds the response. Stored values are never rewritten to labels, so FTS and embeddings keep what the crawler writes today.

**3. `language` column across the producers (R3).**

- **Crawler (`engine/crawler`):**
  - `schema.sql` gets `language TEXT` after `category`.
  - `db.ts`:
    - an additive step in `applyBaseSchema` runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. This is required: `CREATE TABLE IF NOT EXISTS` never adds columns, and without it every existing `crawl.db` fails `sync-whitelist.py`'s superset check against `schema.sql`;
    - the `videos_new` rebuild in `migrateVideos` carries `language`, with the same conditional-expression pattern (`hasLanguage ? "language" : "NULL"`) it uses for the error columns;
    - `VideoUpsertRow` gains `language`, and the upsert gains the column in its INSERT list, in `ON CONFLICT ... language = excluded.language`, and in the positional `run(...)` arguments.
  - `videos-worker.ts`: `PeerTubeVideo` gains a `language` field, a new `extractLanguage` follows R2's rule (object → `id`; non-empty string → itself; otherwise `null`), and `toVideoRow` sets it.
  - `dist/db.js` and `dist/videos-worker.js` are rebuilt with `npm run build` and committed. `test_videos_worker.py` asserts the dist is not stale.
- **Server whitelist DB:**
  - `sync-whitelist.py`: `ensure_content_schema`'s `CREATE TABLE videos` gets `language TEXT`. Copying needs nothing more, because `VIDEO_COLUMNS` is parsed from `schema.sql`, so both `rebuild_content_tables` and `ensure_schema_compatibility` pick the column up automatically.
  - `whitelist_migrations.py`: a new `migrate_videos_language(conn)` checks `_columns` and, if the column is missing, runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is idempotent, keeps every row, and leaves the FTS triggers alone because they do not reference `language`. `migrate_whitelist_schema` calls it after `migrate_videos_schema`, so even a DB that needed the old rebuild ends up with the column.
  - The Python `videos_new` rebuild also carries `language` conditionally. That way no rebuild path can drop it.
- **Updater worker:** `updater-worker.py` merges through `shared_columns`, which works by column name, so it needs no change.

**4. Video page (R6).**

- `video-page.html`: a compact `video-taxonomy` block goes between `video-meta-row` and `video-description`. It holds a category span, a language span and a tags container.
- `index.ts`:
  - `VideoMetadata` gains `tags: string[]`, `category: string` and `language: string`;
  - `fetchVideoMetadataFromServer` fills them from the new keys, keeping only string elements of `tags`;
  - `fetchVideoMetadataFromInstance` fills them from the PeerTube payload (`tags` list, `category.label`, `language.label`);
  - `loadVideo` renders them with `textContent` and `createElement` for the chips, so no HTML is interpolated. Category and language are hidden when empty, and the tag list shows "No tags" when it is empty.
- `video.css` gets compact chip and label styles that reuse the existing metadata sizes and colours.
- `client/frontend/dist` is committed, so it is rebuilt.

**5. Tests (R7).**

- **New `tests/active/test_video_handler.py`.**
  - It loads `sync-whitelist.py` with `spec_from_file_location` (the precedent in `test_repair_video_channel_names.py`) and builds a `tmp_path` DB with its `ensure_whitelist_schema` + `ensure_content_schema`. That is the production schema, triggers included.
  - It imports `handlers.video` with `engine/server` and `engine/server/api` on `sys.path`.
  - The server is a `SimpleNamespace` with `db` (row factory `sqlite3.Row`), `db_lock`, `video_error_threshold` and `popularity_like_weight`. `respond_json` is monkeypatched to capture the status and body.
  - **Fetch stubs, no network:**
    - `fetch_instance_json` is replaced with a path-keyed fake for the success, partial-payload, integration and label cases, and returns `None` for the network-error case;
    - for the malformed-body cases, `video.urlopen` is replaced with a fake response carrying a non-JSON body and a JSON list, and with one that raises `URLError`. This exercises the real parse guard.
  - **Cases:** success, network failure, malformed body, a partial payload keeping tags and category, `tags: []` → `"[]"` / `[]`, two sequential requests with changed source data, and the label mapping (`"15"` → "Science & Technology", unknown id raw, language code → label).
  - **Failure assertions:** a snapshot of the whole `videos` row and the whole `channels` row, taken with `SELECT *` before and after, so every column is compared, not a chosen subset.
- **Migration test.** It builds a legacy `videos` table inline with the pre-change columns (the old shape can only be written out, since the current helpers will create the new one), inserts rows, runs `migrate_whitelist_schema`, and asserts the column exists, the rows are intact, and a second run is a no-op.
- **`test_videos_worker.py`.** The stand-in payload gains `language: {id: "en", label: "English"}` and the test asserts the stored `language`. A second case pre-creates a `crawl.db` without the column, to prove the additive crawler migration.

### Alternatives considered

- **Success signal.** One option is a sentinel or exception from `fetch_instance_video_dynamic`, another is having it return `(ok, data)`. Returning `None` on detail failure is the smallest change and matches how `fetch_instance_json` already reports failure. Checking for "any non-None field" was rejected: a valid source that lacks every optional field would then count as a failure.
- **Two write paths (stats-only vs full).** Rejected, because R2 requires a single UPDATE path. With a single merge, "keep DB when absent" is just "write back the DB value", which leaves the row unchanged.
- **Storing labels instead of ids for language.** Rejected, because R2 fixes the stored value as the code. Resolving at response time keeps the map an honest display concern and lets the upgrade path (per-instance lists) plug in without a data migration.
- **Label map placement.**
  - Inline in `video.py`: rejected, because a ~200-entry language table would bury the handler.
  - A JSON data file: rejected, because it adds a load step and a file path for no gain over a Python literal.
  - One small module is the minimum.
- **Migrating the whitelist DB at Engine startup.** Rejected. The conftest `engine` fixture starts the Engine against the repo's live `engine/server/db/whitelist.db`, so a startup `ALTER TABLE` would change a shared DB from a worktree test run. The migration stays in `migrate-whitelist.py`, the existing operator path. The same applies to the crawler's migration, which only runs when the crawler opens its own DB.
- **Adding `language` to `videos_fts`.** Not required, and it would force an FTS rebuild. Left out.
- **Malformed-body test through `fetch_instance_json` stubs only.** Rejected. A stub that returns a list would test only the handler, not the new parse guard, so those cases stub `urlopen` one level lower.

### Gotchas and risks

- **Deployment order.** After the merge, `fetch_video_row` selects `v.language`. An Engine started on an unmigrated `whitelist.db` answers every `/api/video` with a 500. `sync-whitelist.py` likewise refuses an unmigrated whitelist DB (the exact column check, with the existing "run migrate-whitelist.py" message) and an un-upgraded `crawl.db` (the superset check). The runbook order is:
  1. merge;
  2. run the crawler once, or open `crawl.db` with it, so the additive migration runs;
  3. run `migrate-whitelist.py` on every `whitelist.db`, the prod one included;
  4. restart the Engine.
  
  This goes in `DATA_BUILD.md` / the harvest notes.
- **Unset category shows "Unknown".** When no category is set, PeerTube returns `{id: null, label: "Unknown"}`. R2 takes the label whenever it is non-empty, so such videos store and show "Unknown". The crawler already stores it today, so the data does not change, but the page will now show "Unknown" as a category and the instance-direct fallback will do the same through `category.label`. Language behaves differently: a null id keeps the DB value, so an unset language stays hidden.
- **A removed language never propagates.** PeerTube reports "unset" as a null id, which R2 treats as "keep DB". The same holds for a description cleared to `""` (deliberately kept `pick_text` behaviour) and for title.
- **Uncaught fetch errors.** Exceptions outside the kept contract, such as `ConnectionResetError` or `http.client.IncompleteRead`, still propagate as a 500. They are raised before any write, so the rule that stored data never changes on failure still holds. Widening the catch is a one-line follow-up if wanted.
- **The FTS trigger now fires only on real refreshes.** That is a behaviour improvement, but each successful `/api/video` still rewrites the row's FTS entry, as it does today.
- **Embeddings go stale.** They are not recomputed when tags or category change through `/api/video`. `build-video-embeddings.py` picks the new values up on its next run, as it does today.
- **Column order differs.** A fresh DB has `language` next to `category`, while a migrated DB has it last. Every reader I found uses names (`shared_columns`, named INSERT/SELECT lists, `sqlite3.Row`).
- **The language map is transcribed by hand.** A wrong or missing entry shows the raw code. That is harmless, but it is a fidelity risk.
- **Dist rebuilds.** Crawler dist needs `engine/crawler/node_modules` (`npm install && npm run build`), because `test_videos_worker.py` fails on a stale dist. The client dist rebuild changes hashed asset names in `dist/video-page.html`.

### Tradeoffs the operator accepts

- **Default-only labels (named simplification, R4).** Categories and languages that an instance adds or renames show as raw ids or codes. The ceiling is PeerTube's stock lists. The upgrade path is fetching and caching `/api/v1/videos/categories` and `/api/v1/videos/languages` per instance.
- **Manual migration step.** A deploy needs `migrate-whitelist.py` run before the Engine restarts. The build does not migrate automatically, to keep worktree tests off the shared DB.
- **"Unknown" category and asymmetric removal.** A video with no category shows "Unknown", and a language removed at the source is not cleared. Both follow R2 literally. Changing either means treating a `null` id as "cleared", which is a requirements change.
- **Failed refresh leaves the error visible.** On failure the page shows DB values with no staleness indicator, and `instances.last_error` stays as the last writer left it. This build does not set a new error.

### conflicts

none

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impacts>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_json() (lines 75-87)">
**What changes:** it keeps `urlopen(req, timeout=8)`, the `(HTTPError, URLError, TimeoutError)` catch and the non-200 → `None` return. Two new failure paths return `None` and log at info: a `ValueError` from `.decode("utf-8")` or `json.loads` (this covers both `UnicodeDecodeError` and `JSONDecodeError`), and a parsed value that is not a `dict`.

**What depends on it:** `fetch_instance_video_dynamic` calls it twice, once for the detail and once for the channel. The channel call at line 176 already checks `isinstance(channel_detail, dict)`, so returning `None` for a non-dict does not change it. The new test replaces `video.urlopen` to reach this function directly. `urlopen` is imported by name at line 14, so the monkeypatch must target `handlers.video.urlopen`, not `urllib.request.urlopen`.

**Regression risk: low.** Today a malformed body raises `ValueError` out of `do_GET`. `similar.py:438-441` re-raises anything that is not "interrupted", so the socket closes with no response and the Client proxy sees a transport error, retries once, then answers 502. After this change the same case becomes a DB-fallback 200. Exceptions outside the contract still drop the connection the same way: `ConnectionResetError`, `http.client.IncompleteRead`, `RemoteDisconnected`, and `ssl.SSLError` if it is not wrapped in `URLError`. The plan's "500" wording is inaccurate: there is no 500 handler, the connection just closes. The `# pragma: no cover` on the except line should come off once tests cover it.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic() (lines 162-205)">
**What changes:** it returns `None` when the detail fetch does not give a dict; this is the single success signal. `tags` is no longer coerced with `or []`. New keys: `language` (from `extract_language`), `duration` (from `pick_number(detail.get("duration"))`) and `thumbnail_url`.

**Things to get right:**
- `resolve_asset_url` returns `""`, not `None`, when the value is missing (line 92-93). `thumbnail_url` therefore has to map `""` to `None`, or a payload with no thumbnail overwrites the DB value with `""`. This breaks R2's rule that `None` means "keep the DB value".
- `pick_number` accepts `bool`, because `bool` is a subclass of `int`, so `True` becomes 1. That is harmless for `duration`.
- `account_avatar_url` is already `""`-defaulted and is only used in the response, which is unchanged.
- `channel.get(...)` needs `detail.get("channel")` to be a dict. Today it runs `detail.get("channel") or {}`, and a non-dict truthy `channel` (a string, say) would raise `AttributeError`. This is a pre-existing gap and now worth guarding with `isinstance`, because the function runs only on success.
- Tag strings are not trimmed or deduplicated.

**What depends on it:** only `handle_video_request` (line 227). The grep found no other importer of `handlers.video` apart from `similar.py:84`.

**Regression risk: medium.** This function is the core of R1 and R2. Returning `{}` instead of `None` on failure would reintroduce the "always truthy" defect, but only if the caller keeps the `if dynamic` test. The caller must test `dynamic is None`, not truthiness, or a success whose dict happens to be empty would be treated as a failure.
</impact>
<impact path="engine/server/api/handlers/video.py" element="to_tags_json() (lines 132-137)">
**What changes:** a list returns `json.dumps([string elements])`, and an empty list (or a list of only non-strings) returns `"[]"`. Anything that is not a list returns `None`.

**What depends on it:** only `fetch_instance_video_dynamic`.

**Downstream effects of `"[]"` now being stored in whitelist.db:**
- The FTS trigger indexes `"[]"`, which tokenises to nothing, so it is harmless.
- `build-video-embeddings.parse_tags("[]")` returns `[]` (line 19-26).
- The crawler's `listVideosForTags` treats `'[]'` as missing, but it reads crawl.db, not whitelist.db, so it is unaffected.

**Regression risk: low.** `json.dumps` defaults to `ensure_ascii=True`, which is the same as today, so non-ASCII tags are stored `\u`-escaped. FTS then indexes the escape sequences rather than the words. This is existing behaviour, but it now also applies to refreshed tags, and the crawler (TS `JSON.stringify`) stores raw UTF-8. The build could pass `ensure_ascii=False` to match the crawler. That is a judgment call, so it is flagged here rather than required.
</impact>
<impact path="engine/server/api/handlers/video.py" element="extract_category() (lines 140-146)">
**What changes:** for an object: `label` or `name`, else `str(id)` when the id is not `None`. A number becomes `str(n)`.

**Gap in the current code:** a plain string is returned as-is, including `""` and whitespace. A non-`None` `""` then overwrites the stored category, which R2 forbids ("absent/null keeps DB"). Plain strings should go through `pick_text`. Numbers need a `bool` guard (`isinstance(True, int)` is true).

**PeerTube behaviour:** an unset category is `{id: null, label: "Unknown"}`, which gives "Unknown". That matches the crawler's `extractCategory` (videos-worker.ts:838-848), so the stored value agrees with what the crawler writes.

**Regression risk: low.** Only the dynamic dict uses it.
</impact>
<impact path="engine/server/api/handlers/video.py" element="new extract_language() helper">
**What changes:** a new helper. For an object it returns `id` as a non-empty string; for a plain non-empty string it returns that string; otherwise `None`. A null id (PeerTube's unset `{id: null, label: "Unknown"}`) returns `None`, which keeps the DB value.

**What depends on it:** `fetch_instance_video_dynamic`. It should mirror the crawler's new `extractLanguage` so both producers store the same code.

**Regression risk: low.** Watch for `id` given as a non-string. PeerTube language ids are strings such as `"en"` or `"zh-Hans"`, so use `pick_text` rather than `str()`, so that `0` or `False` never become codes.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_video_row() SELECT (lines 33-69)">
**What changes:** it also selects `v.language`, `v.duration` and `v.thumbnail_url`. `duration` and `thumbnail_url` already exist in both schemas (schema.sql:45-46, sync-whitelist.py:366-367), so only `language` needs the migration.

**What depends on it:** `handle_video_request` only. The row goes into `dict(row)`, so it is read by column name, and column order does not matter.

**Regression risk: high (deployment).** On any whitelist.db that has not been migrated, this SELECT raises `sqlite3.OperationalError: no such column: v.language`. It is not "interrupted", so `similar.py:438-441` re-raises it and the Engine drops the connection on every `/api/video`. What the browser sees:
- The Client proxy retries once, then answers 502 `ENGINE_PROXY_UNAVAILABLE`.
- `fetchVideoMetadataFromServer` returns null, and the page falls back silently to the instance-direct fetch. The failure is visible only in the logs.
- `tests/run-arch-split-smoke.sh:582` and `run-installers-smoke.sh:647` assert 200 and will fail.
</impact>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request(): merge block (lines 226-258) and write block (lines 292-358)">
**What changes:** one merged value set feeds both the response and the UPDATE.
- `dynamic is None` (fetch failed, or `instance_domain` is empty, which today gives `{}` at line 227) skips the whole write block.
- On success the UPDATE SET list gains `language`, `duration` and `thumbnail_url`.

**Things to keep:**
- The merge currently uses `dynamic.get("title") or row.get("title")`, which is falsy-based. For title and description that is fine, because `pick_text` never returns `""`. For numeric and nullable fields keep the existing `is None` pattern.
- `channel_display` falls back to `row["channel_name"]`, and the UPDATE writes it into `videos.channel_name`. Keep that.
- `channels` UPDATE: when `channel_slug` is `None` (no channel in the payload and no `channel_slug` from the join), it writes `channel_name = NULL`. Today it runs on failure too; on success only it still can. This is pre-existing and should be flagged, not changed.
- The `instances` reset runs even when no `instances` row exists for the host; it is a no-op.
- `popularity`: `compute_popularity(views, likes, row["published_at"], ...)`. Keep it.

**Transaction:** `with server.db_lock: with server.db:` commits or rolls back as one unit, so the `OperationalError` catch leaves nothing half-written.

**What depends on it:** `similar.py:495-497`. The `videos_fts_au` trigger fires on every successful UPDATE, including no-op field sets. `last_checked_at` is always bumped on success, so every successful request rewrites the row's FTS entry. That is today's behaviour, now limited to successes.

**Regression risk: high.** This is the heart of R1 and R2. Today a failure still writes: it bumps `last_checked_at`, clears `instances.last_error`, and can set `channels.channel_name` to NULL. After the change, failures stop all of that, and any operational process that relied on those side effects loses them. None was found by grep.
</impact>
<impact path="engine/server/api/handlers/video.py" element="response dict (lines 271-290)">
**What changes:** all 18 existing keys are kept. New keys:
- `tags`: parse the merged `tags_json`, keep string elements only, and give `[]` on NULL, `""`, invalid JSON or a non-list.
- `category`: label via `peertube_labels`, or `""`.
- `language`: label, or `""`.
- `nsfw`: `bool(int)`, or `None`. Stored 0/1 becomes `False`/`True`.
- `duration`: int, or `None`. The stored INTEGER passes through.
- `thumbnailUrl`: string, or `""`.

**What depends on it:**
- The Client proxy passes the body through as bytes (`client/backend/server.py:606-619`).
- `index.ts fetchVideoMetadataFromServer` reads only the keys it knows, so the extra keys are harmless to the current build.

**Regression risk: low.** `tags_json` from the crawler can hold a JSON string rather than a list, which `build-video-embeddings.parse_tags` tolerates by treating it as one tag. The response parser should return `[]` for a non-list, as R5 says. Note that this differs from `parse_tags` on the same input.
</impact>
<impact path="engine/server/api/handlers/video.py" element="helpers resolve_asset_url, pick_text, pick_number, to_nullable_bool (lines 90-159)">
**What changes:** nothing. Their contracts matter to the merge:
- `resolve_asset_url` returns `""` on a missing value and always uses `https://`, while the crawler's `resolveAssetUrl` keeps the crawl protocol and adds a `/` when there is none.
- `pick_text` trims.
- `pick_number` truncates floats and accepts `bool`.
- `to_nullable_bool` maps an unknown type to `None`.

**Regression risk:**
- A refreshed `thumbnail_url` may differ in form from the crawler's (`thumbnailPath` against the crawler's `thumbnailUrl ?? thumbnailPath ?? thumbnail_path ?? thumbnail`). The plan picks `thumbnailUrl or thumbnailPath` only. A PeerTube payload with only `thumbnail_path` or a `thumbnail` object keeps the DB value. That is safe.
- A relative path with no leading `/` gives `https://hostpath`, which is malformed. PeerTube always sends a leading `/`, so this is low risk.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="do_GET statement_deadline (lines 433-441), _dispatch_get /api/ rate limit (447-449), /api/video route (495-497)">
**What changes:** nothing in code, but this interaction was not in the plan.

**Deadline:** `/api/video` runs inside `statement_deadline(statement_timeout_seconds)`, 5 s by default. The deadline is an absolute thread-local time set at request start (`data/db.py:44-64`). The two outbound fetches (up to 8 s + 8 s) run before the UPDATE, so for any instance slower than about 5 s in total:
- the UPDATE, and the triggers it fires, raise `OperationalError('interrupted')`;
- the handler's existing catch logs a warning and answers 200 with the fresh values, but nothing is persisted.

A slow instance can therefore never be refreshed in the DB. This is today's behaviour as well, and the handler's `OperationalError` catch is what keeps it a 200. The new tests use a `SimpleNamespace` server with no deadline, so they will not show this.

**Rate limit:** `/api/` routes, `/api/video` included, go through the Engine's 60/min per-IP limiter. The earlier assumption that it is not rate-limited is wrong. A 429 is answered before the handler runs.

**What depends on it:** every `/api/video` request.

**Regression risk: medium (latent).** The DB-write guarantee is best-effort for slow sources. Document it; widening the deadline is out of scope.
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline / install_deadline_handler / connect_db (lines 31-81)">
**What changes:** nothing.

**What depends on it:** `server.db` carries the progress handler. The new handler test builds its own `sqlite3.connect` without it, so it runs with no deadline.

**Regression risk:** none from the build. The test cannot cover the deadline behaviour described in the `similar.py` entry.
</impact>
<impact path="engine/server/data/peertube_labels.py" element="new module: category map, language map, two lookup functions">
**What changes:** a new stdlib-only module holding:
- `CATEGORY_LABELS`: `"1"`–`"18"`, exactly R4's list, including `"11": "News & Politics"`, `"12": "How To"` and `"15": "Science & Technology"`.
- a language-code map copied from stock PeerTube.
- a category lookup: digit-only strings go through the map, and anything else or an unknown id is returned unchanged.
- a language lookup: known codes resolve, and unknown codes are returned raw.

It follows the `engine/server/data/*.py` style (a module docstring, `from __future__ import annotations` as in `whitelist_migrations`), with a docstring on every function.

**What depends on it:** the video.py response builder only, which imports it as `from data.peertube_labels import ...`, matching the existing `from data.time import now_ms`.

**Regression risk: low.**
- The map is transcribed by hand, so there is a fidelity risk.
- PeerTube language codes are case-sensitive (`zh-Hans`, `zh-Hant`, `pt-PT`), so the lookup must not lowercase.
- Use `str.isdigit()` together with `isascii()`, or a Unicode digit such as `"١٥"` counts as digit-only. Harmless, since the result is an unknown id returned raw.
- The Engine imports `data.*` at startup, so the module must do no work at import beyond the literals.
</impact>
<impact path="client/backend/server.py" element="PROXY_READ_GET_ROUTES / PROXY_ALLOWED_QUERY_PARAMS['/api/video'] (lines 81-88) and _proxy_engine_request (570-680)">
**What changes:** nothing. The body is passed through as bytes, and `row_filter` is `None` for `/api/video`.

**What depends on it:** the page. `ENGINE_PROXY_TIMEOUT_SECONDS = 10` with `ENGINE_PROXY_RETRY_COUNT = 1`. The Engine's `/api/video` can take up to 16 s on a slow source, which exceeds the proxy timeout. The proxy then retries, so a second Engine request (and possibly a second write) runs for the same page view. This is pre-existing; it is noted because each successful request now writes more columns.

**Regression risk: none from the code.** An unmigrated DB turns into a 502 here, as described in the `fetch_video_row` entry.
</impact>
<impact path="engine/crawler/schema.sql" element="videos CREATE TABLE (lines 29-61)">
**What changes:** `language TEXT` is added after `category` (line 42).

**What depends on it:**
- `sync-whitelist.py` parses the column list at import (lines 92-96), so `VIDEO_COLUMNS` gains `language`. This drives the exact check against the whitelist DB, the superset check against crawl.db, and the copy column list.
- `db.ts` runs `schemaSql` twice in `applyBaseSchema`.
- `updater-worker.init_staging_db` creates staging from it (lines 548-565).
- `tests/active/test_videos_worker.py` and `test_repair_video_channel_names.py` build crawl-shaped DBs from it.

**Regression risk: medium.** `CREATE TABLE IF NOT EXISTS` never adds the column to an existing crawl.db. The first `db.exec(schemaSql)` in `applyBaseSchema` also runs every `CREATE INDEX` against the old table, so no index on `language` may be added to schema.sql, or the first exec fails on old DBs before the migration can run. The parser splits on top-level commas; a plain `language TEXT,` line parses cleanly.
</impact>
<impact path="engine/crawler/src/db.ts" element="applyBaseSchema() (lines 65-71): new additive language step">
**What changes:** after `migrateVideos(db)` and before the second `db.exec(schemaSql)`, a step checks `getColumns(db, "videos")` and runs `ALTER TABLE videos ADD COLUMN language TEXT` when the column is missing. It must run after `migrateVideos`, so that a rebuilt table is also covered, and it must be guarded with `tableExists`.

**What depends on it:** every store constructor: `CrawlerStore` (line 520), `ChannelStore` (792) and `VideoStore` (1203). Any crawler CLI that opens crawl.db migrates it: instances, channels, videos, counts. `openExistingDb` (videos-worker.ts:940) opens the prod DB read-only with no migration, and only reads `video_id`, so it is safe.

**Regression risk: medium.** It is the only way an existing crawl.db can pass `sync-whitelist`'s superset check. `ALTER ADD COLUMN` is a cheap metadata change, but it needs a write lock, and a concurrently running crawler process sharing crawl.db will contend. The column lands last on migrated DBs; all readers use column names.
</impact>
<impact path="engine/crawler/src/db.ts" element="migrateVideos() rebuild (lines 277-399)">
**What changes:** a `hasLanguage` flag and a `languageExpr` (`"language"` or `"NULL"`); `language TEXT` in the `videos_new` CREATE; `language` in the INSERT and SELECT column lists.

**What depends on it:** only very old crawl.db files that lack the error columns reach this rebuild.

**Regression risk: low.** The column lists here are positional pairs, so an INSERT/SELECT that is out of step would silently shift data. Keep the three lists aligned.
</impact>
<impact path="engine/crawler/src/db.ts" element="VideoUpsertRow (lines 465-491), VideoStore upsertStmt (1138-1196), upsertVideos (1453-1487)">
**What changes:** a `language: string | null` field. The INSERT column list gains `language`. The VALUES list grows from 25 to 26 `?`, and must stay aligned with `NULL, NULL, 0` for the error columns. The ON CONFLICT clause gains `language = excluded.language`, and the positional `run(...)` gains `row.language` at the matching position.

**What depends on it:** `toVideoRow` builds the row.

**Regression risk: medium.**
- A positional mismatch between the column list, the `?` count and the `run()` arguments shifts every column after it. SQLite reports a count mismatch as an error, but not a mis-ordering.
- **Behaviour:** `language = excluded.language` makes a re-crawl overwrite the stored language with NULL when the listing payload carries `{id: null}`. That is consistent with how the crawler treats `category`, but it differs from the handler's "null keeps DB" rule. A crawl can therefore erase a language the Engine learned. Only crawl.db is affected; whitelist.db is rebuilt from it by sync, see the sync entry.
- `listExistingVideoIds` and `--new-videos` skip videos that already exist, so updater crawls never fill in `language` for existing rows. Existing rows get a language only from a full re-crawl or from `/api/video` views (whitelist.db only).
</impact>
<impact path="engine/crawler/src/db.ts" element="listVideosForTags / updateVideoTags / updateVideoInvalid / updateVideoError (lines 1283-1539)">
**What changes:** nothing.

**What depends on it:** the tags enrichment writes only `tags_json`, so language is not touched.

**Regression risk: none.**
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="PeerTubeVideo interface (lines 84-118), new extractLanguage(), toVideoRow() (lines 648-709)">
**What changes:**
- `PeerTubeVideo` gains `language?: PeerTubeLanguage | string`, where `PeerTubeLanguage` is `{ id?: string | null; label?: string }`, modelled on `PeerTubeCategory` at lines 78-82.
- `extractLanguage`: an object gives `id` via `toNullableString`, a string gives itself via `toNullableString`, anything else gives `null`. It is placed next to `extractCategory` in the same style and carries a docstring comment.
- `toVideoRow` sets `language: extractLanguage(video.language)`.

**What depends on it:** `crawlChannelVideos` → `upsertVideos`. The PeerTube channel-videos listing does include `language`, so it is captured on the normal crawl path.

**Regression risk: low.** Match the handler's rule exactly, including that a numeric id gives `null`. `toNullableString` rejects numbers, which is consistent with the handler using `pick_text`.
</impact>
<impact path="engine/crawler/dist/db.js" element="compiled db module (VideoStore upsert line ~1100+, migrateVideos ~268, applyBaseSchema)">
**What changes:** regenerated by `npm run build` (`tsc -p tsconfig.json`) and committed with the source.

**What depends on it:** production runs the dist, not the source. That covers `updater-worker.py` through `dist/videos-cli.js` (lines 952-982), `npm run crawl:*` and `run-dataset-build.sh`, plus `test_videos_worker.py`.

**Regression risk: medium.** `test_videos_worker._dist_is_stale` compares only `videos-worker.ts` with `videos-worker.js`. A stale `db.js` is not caught by the staleness gate. It would show up only as `language` missing from the upsert (the new assertion) or as a superset-check failure later. Rebuild and commit both, and check the diff.
</impact>
<impact path="engine/crawler/dist/videos-worker.js" element="compiled crawlVideos / toVideoRow / extractLanguage">
**What changes:** regenerated and committed.

**What depends on it:** `test_videos_worker.py` imports it, and its staleness gate checks this pair.

**Regression risk: medium, for the suite.** The rebuild needs `engine/crawler/node_modules` (typescript and better-sqlite3). `tsc` recompiles all of `src/`, so any other dist file already out of step (for example `host-filters.js`, which `test_host_normalisation.py` checks) will change in the same commit. Review the full dist diff.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="ensure_content_schema() CREATE TABLE videos (lines 350-383)">
**What changes:** `language TEXT` after `category`.

**What depends on it:**
- `main()` line 597 on every sync.
- `test_repair_video_channel_names.py:70,134` builds its whitelist shape from this.
- The new handler test and the migration test build from it.
- `repair-video-channel-names.py` loads the module lazily.

**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` does nothing on an existing whitelist.db, so the column on existing DBs comes only from the migration. The exact check then enforces it (next entry).
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="VIDEO_COLUMNS (line 96), ensure_schema_compatibility() (186-216), rebuild_content_tables() (448-522)">
**What changes:** nothing in code. `language` flows in from schema.sql.

**Behaviour:**
- The exact check (`VIDEO_COLUMNS + ["popularity"]`) rejects an unmigrated whitelist.db with "missing columns: language ... Run migrate-whitelist.py".
- The superset check rejects a crawl.db the crawler has not opened with "Update the crawl DB ...".
- The copy (`INSERT INTO videos (cols) SELECT cols FROM source.videos`) uses column names, so order does not matter.

**Regression risk: medium (operational).**
- `rebuild_content_tables` runs `DELETE FROM videos` and reloads from crawl.db. Every `/api/video` refresh in whitelist.db (tags, category, language, `last_checked_at`) is therefore thrown away on the next sync, unless the crawler has since stored the same values. The "persisted" metadata lasts only until the next dataset build. This is pre-existing for the other fields, and it now matters for `language` because crawl.db rarely has it for existing rows.
- `scripts/run-dataset-build.sh:227-228` runs sync against an existing whitelist.db without migrating it first, so the first build after merge fails at the exact check until `migrate-whitelist.py` has run.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="VIDEOS_FTS_TRIGGERS_SQL / ensure_content_schema videos_fts (lines 270-417)">
**What changes:** nothing. The FTS index and the triggers cover `title, description, tags_json, category, channel_name`, not `language`, which is the plan's decision.

**What depends on it:** the handler's UPDATE fires `videos_fts_au`.

**Regression risk: none.** `ALTER TABLE ADD COLUMN` on `videos` leaves the triggers and the external-content FTS valid.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="migrate_videos_schema() rebuild (lines 232-370)">
**What changes:** it carries `language` conditionally, the same way the error columns are carried: `language TEXT` in `videos_new`, and `language` / `{language_expr}` in the INSERT and SELECT lists.

**What depends on it:** `migrate_whitelist_schema`.

**Regression risk: medium.** This rebuild also runs `DROP TABLE IF EXISTS video_embeddings` and drops `videos_fts` and its triggers (lines 262-266). A migration test whose inline legacy table lacks `last_error`, `last_error_at` or `error_count` takes this destructive path. Build the legacy fixture with the error columns present and only `language` missing, to test the additive path in isolation, or assert the rebuild path on purpose. As with db.ts, the positional lists must stay aligned.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="new migrate_videos_language(conn) and migrate_whitelist_schema() (lines 373-377)">
**What changes:** a new function. It returns early if the `videos` table does not exist (`_table_exists`); if `language` is not in `_columns(conn, "videos")` it runs `ALTER TABLE videos ADD COLUMN language TEXT`. It is called last in `migrate_whitelist_schema`. Precedent: `recompute-popularity.ensure_popularity_schema` (lines 18-25) does the same kind of additive ALTER.

**What depends on it:** `migrate-whitelist.py:87`, which runs inside `with conn:`.

**Regression risk: low.** It is idempotent. The signature is `migrate_whitelist_schema(conn, table_name)`, so the test must pass `"instances"`. The FTS index is left alone: `videos_fts` is external content over named columns.
</impact>
<impact path="engine/server/db/jobs/migrate-whitelist.py" element="main() (lines 72-91)">
**What changes:** nothing in code. It now also adds `language`.

**What depends on it:** the operator runbook. It must run on every whitelist.db (prod, dev, the one symlinked into worktrees) before the new Engine starts. It takes a backup by default (a full file copy of a large DB).

**Regression risk: low (code), high (process).** The step is manual, and forgetting it breaks `/api/video` everywhere and makes `sync-whitelist` refuse to run. It imports `server.db.jobs.whitelist_migrations` with `engine_dir` on the path.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="merge column intersection (lines 142-158) with merge_rules.json videos INSERT_ONLY">
**What changes:** nothing.

**Behaviour:** `merge_columns = [c for c in prod_columns if c in stage_columns]`. Staging is created from schema.sql and has `language`. If prod is unmigrated, `language` is silently dropped from the merged new rows, with no error. Because `videos` is INSERT_ONLY, existing prod rows never receive `language` from the updater.

**What depends on it:** the updater cycle.

**Regression risk: low.** It fails soft. It is one more reason to migrate prod first. The plan says "updater-worker merges through shared_columns"; the merge that matters is in `merge-staging-db.py`, and `shared_columns` in the updater only seeds `channels`.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="init_staging_db (548-565), seed_staging_from_prod / shared_columns (568-619), crawler dist invocation (952-982)">
**What changes:** nothing.

**What depends on it:** staging is created from the new schema.sql. The crawler dist, once rebuilt, writes `language` to staging. The updater restarts the Engine after the merge. If prod whitelist.db is not migrated by then, the restarted Engine serves broken `/api/video`.

**Regression risk: low (code), medium (process).**
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="parse_tags / build_text (lines 19-54), queries (187-205)">
**What changes:** nothing. It reads `tags_json` and `category` by name, and not `language`.

**Regression risk: none.** `"[]"` parses to no tags. Embeddings are not recomputed on refresh; that is the plan's accepted staleness.
</impact>
<impact path="engine/server/data/search.py" element="FTS lexical query / row projection (lines 60-70)">
**What changes:** nothing. It uses explicit columns.

**Regression risk: none.** It reflects refreshed tags and category through the triggers.
</impact>
<impact path="engine/server/db/jobs/repair-video-channel-names.py" element="lazy load of sync-whitelist.py">
**What changes:** nothing.

**What depends on it:** it loads `sync-whitelist.py`, which parses schema.sql at import. Its UPDATE touches only `channel_name`.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="create_table_and_indexes_from_source / copy_and_prune_prod (lines 198-340)">
**What changes:** nothing. It copies the table DDL from the source DB and then runs `INSERT ... SELECT *`, so the shapes always match.

**Regression risk: low.** If the source prod is unmigrated, the mini-prod lacks `language`, and the merge silently drops it (see the merge entry).
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="hand-written CREATE TABLE videos (line 157)">
**What changes:** nothing. It never calls `fetch_video_row` or the sync schema checks.

**Regression risk: none.** Listed so nobody "fixes" it.
</impact>
<impact path="tests/active/conftest.py" element="engine fixture on WHITELIST_DB (lines 34, 105-145); sys.path with client/backend first (37-43)">
**What changes:** nothing.

**What depends on it:**
- **Engine fixture.** The session Engine runs on the worktree's `engine/server/db/whitelist.db`, which is shared with main. No `tests/active` file calls `/api/video` (grep), so the suite stays green on an unmigrated DB, but a manual or smoke run does not.
- **Imports in the new handler test.** `handlers.video` does `from http_utils import respond_json`. `client/backend` holds only `server.py` and `lib/`, so a top-level `http_utils` resolves to `engine/server/api/http_utils.py` once that is on `sys.path`. `server` is already cached as the Client module, and `video.py` does not import `server`.

**Regression risk: low.** Do not make the Engine migrate the DB at startup (plan decision): that would ALTER the shared DB from a worktree run.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_video_proxy check (line 582)">
**What changes:** nothing.

**What depends on it:** it expects `/api/video` to answer 200 through the Client on the live whitelist.db.

**Regression risk: medium.** It fails until `migrate-whitelist.py` has run on that DB. `tests/run-installers-smoke.sh:647` has the same check, with `|| true`, so it only reports.
</impact>
<impact path="scripts/run-dataset-build.sh" element="stages crawl:videos:tags (215) → sync-whitelist (227-228)">
**What changes:** nothing.

**What depends on it:** the tags stage opens crawl.db through `VideoStore`, so the additive crawler migration runs automatically. The sync stage then fails on an unmigrated existing whitelist.db.

**Regression risk: medium (operational).** The runbook, or the script, needs a `migrate-whitelist.py` step before sync. Adding it to the script is outside the plan; document it.
</impact>
<impact path="client/frontend/video-page.html" element="player-info block between video-meta-row (68-95) and video-description (96)">
**What changes:** a new `video-taxonomy` block with category and language spans and a tags container.

**What depends on it:** `index.ts` looks the elements up by id at module top (lines 22-48 pattern).

**Constraints:**
- The CSP (line 8) has `style-src 'self'`, so there are no inline `style=` attributes. Hide elements with the `hidden` attribute or a class.
- Use a semantic list or `role` for the chips, and an `aria-label` for the tags region.

**Regression risk: low.**
- Issue 14 (collapsible description) edits the adjacent `video-description` markup, CSS and fill code, so a merge conflict is likely if both are open.
- `client/frontend/dist/video-page.html` is the built copy (see the dist entry).
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="VideoMetadata type (481-501), fetchVideoMetadataFromServer (517-555), fetchVideoMetadataFromInstance (560-625), loadVideo (85-229), element lookups (22-48)">
**What changes:**
- `VideoMetadata` gains `tags`, `category` and `language`.
- The server path reads `data.tags` (array filtered to strings), `data.category` and `data.language`, with `""` or `[]` defaults.
- The instance path reads `data.tags`, `(data.category as {label}).label` and `(data.language as {label}).label`, with type guards because the payload is `Record<string, unknown>`.
- `loadVideo` renders with `textContent` and `createElement` / `replaceChildren` for the chips.

**Details to get right:**
- **Null metadata.** When both fetches fail, `metadata` is `null`. The block should then be hidden, or show "No tags", consistently. Decide which.
- **"Unknown" asymmetry.** For an unset language, PeerTube sends `{id: null, label: "Unknown"}`. The server path hides it: the stored value is NULL, which becomes `""`. The instance fallback shows "Unknown" through `language.label`, so the two paths disagree. Treat a null `id` as empty on the instance path too, or accept the difference and document it.
- **Category "Unknown".** It shows on both paths.
- **Existing HTML interpolation.** Existing rendering uses `innerHTML` with `escapeHtml` elsewhere. The new code must not interpolate tags into `innerHTML`.

**Regression risk: low.** `fetchVideoMetadataFromServer` returns null on `!response.ok`, which already covers the 502 case.
</impact>
<impact path="client/frontend/src/video.css" element="new .video-taxonomy / chip styles near .video-meta-row (309-347) and .metric (325-332)">
**What changes:** compact label and chip rules that reuse `--line`, `--muted`, `--accent-strong`, the `rgba(180, 87, 55, 0.08)` background, `border-radius: 999px` and 0.8–0.9rem font sizes.

**Gotcha:** an author `display:` rule overrides the UA `[hidden]{display:none}`. `.instance-meta` (`display: inline-flex`) already has this latent bug. If the new spans get `display: inline-flex` or `flex`, add an explicit `.video-taxonomy [hidden] { display: none; }` or equivalent, or `hidden = true` will not hide them. The existing `:empty` pattern (lines 304-307) is an alternative.

**Regression risk: low.**
</impact>
<impact path="client/frontend/dist" element="committed build output: video-page.html, assets/video-*.js, assets/video-*.css">
**What changes:** a rebuild with `vite build` (`npm run build`). The hashed asset names change, `dist/video-page.html` references the new names, and the old `video-gjYm1MC8.js` and `video-ypOuFwNw.css` become orphans to delete. Shared chunks may be re-hashed too.

**What depends on it:** production serving. DEPLOYMENT.md:301 says to re-run the rsync after every build.

**Regression risk: low.** Commit a consistent set. No `tests/active` test reads the dist; the frontend tests bundle `src` with esbuild.
</impact>
<impact path="tests/active/test_video_handler.py" element="new test module (handler, labels, migration)">
**What changes:** a new file.

**Imports:**
- It loads `sync-whitelist.py` through `importlib.util.spec_from_file_location`, under a unique module name. `test_repair_video_channel_names.py` uses `sync_whitelist_channel_names` and `test_host_normalisation` uses `sync_whitelist_job`.
- It inserts `engine/server` and `engine/server/api` into `sys.path` and does `from handlers import video`. This works in-process, as `test_internal_events.py:37` does: `video.py` imports no numpy or faiss (`data.time`, `data.popularity`, `http_utils`).

**Fixture DB:**
- A `tmp_path` DB with `ensure_whitelist_schema` + `ensure_content_schema`, and `row_factory = sqlite3.Row`, so that `dict(row)` works.
- `videos` needs `last_checked_at` (NOT NULL). `instances` needs `last_error`, `last_error_at` and `last_error_source` set to non-NULL for the failure assertions.
- A `channels` row with a matching `channel_id`.

**Stand-in server:** `db`, `db_lock` (`threading.Lock`), `video_error_threshold` and `popularity_like_weight`.

**Monkeypatch targets:** `video.respond_json`, `video.fetch_instance_json` (path-keyed), and `video.urlopen` for the parse-guard cases. The fake response must support `with`, `.status` and `.read()`.

**Assertions:**
- Whole-row `SELECT *` snapshots before and after, for failure.
- `last_checked_at` is strictly greater than a seeded old value. Seed it well in the past, not with `now_ms()`, to avoid equal-millisecond flakes.

**Regression risk: low for production, medium for suite stability.**
- It must never use the `engine`/`dataset` fixtures or `WHITELIST_DB`.
- A `urlopen` fake that raises `URLError` checks the kept network contract.
- A `channel` in the payload triggers a second `fetch_instance_json` call, so the path-keyed fake must answer `/api/v1/video-channels/...` or return `None`.
</impact>
<impact path="tests/active/test_videos_worker.py" element="test_crawl_writes_each_hosts_own_channel_name and a new additive-migration case">
**What changes:**
- The alpha payload items gain `language: {id: "en", label: "English"}`, and the SELECT and assertion include `language`.
- A second case pre-creates crawl.db with the old videos DDL. It has to be written inline, because schema.sql will already contain `language`. It then runs `crawlVideos` and asserts the column exists and is filled.

**What depends on it:**
- node on PATH, `engine/crawler/node_modules` (better-sqlite3) and a fresh dist.
- The `_dist_is_stale` gate covers only the `videos-worker` pair.
- The test builds its DB with `conn.executescript(SCHEMA...)`, so the new-schema case never exercises the ALTER. The second case is the one that proves the migration.

**Regression risk: medium.** The node, dist and node_modules requirements are hard, and missing ones fail rather than skip. Keep one test per claim, and keep the module docstring bullets in the file's style.
</impact>
<impact path="tests/active/test_repair_video_channel_names.py" element="crawl/whitelist fixtures built from schema.sql and ensure_content_schema">
**What changes:** nothing. The inserts name their columns, and the new nullable column is harmless.

**What depends on it:** it is the precedent for the `_load_job` loader the new test copies.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_host_normalisation.py" element="dist staleness gate for host-filters (_dist_is_stale)">
**What changes:** nothing.

**Regression risk: low.** `npm run build` rewrites every dist file. If `host-filters.js` changes, commit it; by commit time it is then newer, not stale.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (lines 133-139)">
**What changes:** at harvest:
- Map `test_video_handler.py` to `engine/server/api/handlers/video.py`, `engine/server/data/peertube_labels.py`, `engine/server/db/jobs/whitelist_migrations.py` and `engine/server/db/jobs/sync-whitelist.py`.
- Extend `test_videos_worker.py`'s entry with `engine/crawler/src/db.ts`, `engine/crawler/dist/db.js` and `engine/crawler/schema.sql`. Today it lists only the videos-worker pair, so a `db.ts`-only change would not re-run it.

**Regression risk: low.** The file is local and gitignored.
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record (and tests/last_test_output.txt)">
**What changes:** both are regenerated by `validate_tests.py`.

**Regression risk: none functionally.** They conflict on merge: take main's copy and re-run with `--compare`.
</impact>
</impacts>


### docs_checklist


<doc path="DATA_BUILD.md">
Sections 1 and 2:
- Add a note that the crawler adds `videos.language` (the PeerTube language code) to an existing `crawl.db` the first time any crawler command opens it.
- Add a note that `sync-whitelist.py` refuses a `crawl.db` the crawler has not opened yet (superset check).
- Add a note that `sync-whitelist.py` refuses an existing `whitelist.db` until `migrate-whitelist.py` has added the column.
- Beside the existing `migrate-whitelist.py` block (lines 155-158), add the upgrade order: merge; open or run the crawler once on `crawl.db`; run `migrate-whitelist.py` on every `whitelist.db`, prod included; then restart the Engine.

Two notes for step 2:
- `run-dataset-build.sh` does not migrate on its own.
- Refreshes made by `/api/video` in `whitelist.db` are replaced by the next sync.
</doc>
<doc path="engine/server/README.md">
Line 9 (`/api/video`) should describe:
- **Refresh.** One source fetch refreshes and persists title, description, stats, tags, category, language, nsfw, duration and thumbnail.
- **Failure.** A failed or malformed source leaves the DB untouched and answers from the DB.
- **Response keys.** The new keys are `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Category and language are mapped to PeerTube default labels.
- **Migration.** The whitelist DB must be migrated (`language` column).
</doc>
<doc path="DEPLOYMENT.md">
**Line 374:** optionally note that `/api/video` writes back to `whitelist.db` only when the source answers inside the request's statement budget.

**Upgrade notes:** add a short note, or a Triage row, for this deploy:
- Before restarting the Engine, run `migrate-whitelist.py` on the Engine's `whitelist.db`.
- Symptom when it is skipped: every video page falls back to direct-instance metadata. The Client proxy logs 502 `ENGINE_PROXY_UNAVAILABLE` on `/api/video`, and the Engine journal shows `no such column: v.language`.
</doc>
<doc path="docs/project/roadmap.md">
Implementation-order step 2 (line 142) refers to feed-panel I1 language capture.
- This build already captures `videos.language` (the code), so I1 is partly delivered under a different column name than plan 04 proposes.
- Update the step so it names what remains: label storage if needed, backfill I3, and the filter I2.
- Note that existing rows get a language only from a full re-crawl or from video-page views.
</doc>
<doc path="docs/project/plans/archive/04-feed-parameter-panel.md">
I1 (lines 19-20, 47-48) specifies `language_id` + `language_label`. Record, or link from the roadmap, that `language` (code only) now exists and that labels resolve at read time through `engine/server/data/peertube_labels.py`, so that I1 does not add a duplicate column.
</doc>
<doc path="docs/project/plans/18-english-subtitles.md">
Lines 20, 43 and 90 say the `videos` table stores no language and that there is "no language column to select by". After this build both statements are false. Update them, noting that coverage is sparse for existing rows.
</doc>
<doc path="docs/project/issues/10-video-metadata-completeness.md">
At harvest on main, not in this worktree:
- Set `Status: enhancement, complete` and append a delivery comment.
- Record the accepted limits: default-only labels; "Unknown" category; removals of language and description are not propagated; persistence is best-effort under the 5 s statement deadline; refreshes are lost at the next sync.
- Move the file to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/issues/14-collapsible-description.md">
No content change is needed. Note at harvest that the video page now has a taxonomy block between `video-meta-row` and `video-description`. Issue 14 edits the adjacent markup, CSS and fill code, so expect a merge conflict.
</doc>


### highest_risk


engine/server/api/handlers/video.py fetch_video_row(): once it selects `v.language`, every unmigrated whitelist.db (prod, dev, and the one the worktrees share) raises `no such column`. `similar.py` re-raises that error, so the Engine drops the connection on every `/api/video`, and the Client proxy answers 502. The page falls back to instance-direct silently, and both smoke scripts fail. The only guard is the manual `migrate-whitelist.py` step before the Engine restarts, and `run-dataset-build.sh` / `sync-whitelist.py` also refuse to run until it is done.
engine/server/api/handlers/video.py handle_video_request / fetch_instance_video_dynamic: the single success signal must be tested as `dynamic is None`. Every `""` value must be mapped to None before the merge, or `""` overwrites stored data despite R2: this covers `resolve_asset_url`'s `""` thumbnail and `extract_category`'s plain `""`. Separately, the whole write runs inside the request's 5 s statement deadline after up to 16 s of outbound fetches, so slow sources answer 200 with fresh values but never persist. The stubbed tests cannot show this.
engine/crawler/src/db.ts upsert and additive migration, and dist/db.js: the 26-slot positional INSERT, VALUES and `run()` lists must stay aligned, and the ALTER must run after `migrateVideos` and before the second schema exec. `language = excluded.language` lets a re-crawl wipe a language to NULL. `test_videos_worker.py`'s staleness gate checks only `videos-worker.js`, so an unrebuilt `db.js` ships silently. It would surface only as a missing language, or as a `sync-whitelist` superset failure on production crawl.db.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I opened the files the inventory cites and checked its claims against them: `video.py`, `similar.py`, `data/db.py`, `whitelist_migrations.py`, `migrate-whitelist.py`, `sync-whitelist.py`, the crawler's `db.ts` and `videos-worker.ts`, `merge-staging-db.py`, `test-orchestrator-smoke.py`, `test_videos_worker.py`, `conftest.py` and the video page `index.ts`. Every entry I checked holds. The plan works as designed. Its risk is operational (migration order), not a design flaw. Nothing in the tree contradicts the requirements or the settled plan, and I found no impact the inventory does not already carry.
<question id="1">
Yes. Today `fetch_instance_video_dynamic` turns a failed detail fetch into `{}` via `or {}` (video.py:164). The write block runs whenever that dict is truthy (line 293), so the missing single success signal is exactly where the plan puts it. Returning `None` and testing `dynamic is None` restores it, and the merge at lines 229-258 already uses the "None keeps DB" pattern the plan extends. Three implementation details, all already in the inventory, decide whether R2 holds in practice:
- `thumbnail_url` must map `resolve_asset_url`'s `""` to `None` (lines 92-93).
- `extract_category` must pass plain strings through `pick_text`, because line 145 returns `""` as-is.
- `channel` needs an `isinstance(dict)` guard.

The crawler side works too:
- The upsert has exactly 25 `?` plus `NULL, NULL, 0` (db.ts:1168).
- `applyBaseSchema` runs `schemaSql`, the migrations, then `schemaSql` again (lines 65-71), so the additive step fits between `migrateVideos` and the second exec.
- The sync column lists come from schema.sql (`VIDEO_COLUMNS`, line 96), so the copy picks `language` up without edits.

The test design is sound:
- `http_utils` resolves only to `engine/server/api/http_utils.py`, because the client copy lives under `lib/`.
- `data/__init__.py` and `data/popularity.py` import nothing heavy.
- The name `peertube_labels` does not collide with anything, and no label map exists anywhere yet.
</question>
<question id="2">
- **Deployment coupling.** The new `v.language` in `fetch_video_row` raises `OperationalError`. It is not "interrupted", so `do_GET` re-raises it (similar.py:438-440) and every `/api/video` drops its connection until `migrate-whitelist.py` has run. `sync-whitelist.py` refuses to run through the exact and superset checks (lines 186-216), and `run-dataset-build.sh` fails at sync.
- **Refreshes are short-lived.** `rebuild_content_tables` reloads `videos` from crawl.db on every sync, so a refresh lasts only until the next dataset build.
- **Slow sources are never persisted.** The 5 s `statement_deadline` is armed before the handler runs (similar.py:436), so a source slower than that is fetched but not saved.
- **Crawler and Engine disagree on unset language.** The crawler's `language = excluded.language` overwrites with NULL, while the Engine's "null keeps DB" rule does not.
- **Failures stop writing.** Failed refreshes no longer bump `last_checked_at`, clear `instances.last_error*`, or null `channels.channel_name`. Grep finds nothing that relies on those side effects.
</question>
<question id="3">
Before the new Engine serves, `migrate-whitelist.py` must run against every whitelist.db, and the crawler must open crawl.db once. The runbook and `run-dataset-build.sh` need that step before sync.

Both dists must be rebuilt and committed:
- **Crawler dist:** `db.js` too. The staleness gate at test_videos_worker.py:38 checks only the videos-worker pair.
- **Client dist:** orphaned hashed assets are removed.

Two things stay unchanged:
- The migration test's legacy fixture keeps the error columns. Otherwise `migrate_videos_schema` takes its destructive rebuild path, which drops `videos_fts` and `video_embeddings` (whitelist_migrations.py:262-266).
- The Engine does not migrate at startup, because the conftest Engine runs on the shared `WHITELIST_DB` (conftest.py:34).
</question>
<question id="4">
- **Failure path.** A failed or malformed source used to still write the row and clear instance errors. Now it writes nothing and returns the DB values. A malformed body used to drop the connection (the proxy then answered 502, and the page fell back to fetching from the instance directly); now it returns a 200 built from the DB.
- **Refresh scope.** A successful refresh now also writes `language`, `duration` and `thumbnail_url`.
- **Empty tags.** An empty tag list is stored as `"[]"` instead of being skipped.
- **Category values.** A category object with no label now stores its id as a string.
- **Response.** It gains `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Every existing key is kept.
- **Page.** The video page shows category, language and tag chips.
- **Schemas.** crawl.db and whitelist.db each gain a nullable `language` column.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Write the three R2 guards the inventory found into the phase plan as explicit tasks, each with a test case: `thumbnail_url` `""`→`None`, `extract_category` plain strings through `pick_text` (with a `bool` guard on numbers), and an `isinstance(dict)` guard on `channel`. Cost: about three lines of handler code and three small test cases. Without them, a partial payload can blank a stored thumbnail or category, which violates R2.
2. Add a `migrate-whitelist.py` step to `scripts/run-dataset-build.sh` before the sync stage, not only to the runbook. Cost: one script line, and it adds a file outside the plan's four parts, so it needs your approval. The step backs up by default (a full copy of a large DB) unless it is passed `--no-backup`. If you decline, the first dataset build after merge fails at the exact column check until someone runs the migration by hand.
3. Choose one fix for the "Unknown" language mismatch: on the instance-direct fallback, treat a null `language.id` as empty, so the server path and the fallback both hide an unset language. Cost: one guard in `fetchVideoMetadataFromInstance`. The alternative costs nothing but a line in the harvest notes explaining why the two paths show different things.
4. Decide on `json.dumps(..., ensure_ascii=False)` for refreshed tags, to match the crawler's raw UTF-8 so FTS indexes words rather than `\u` escapes. Cost: one argument. This is a behaviour change beyond the requirements, so leave it out unless you want it.
5. Fix the "500" wording in the plan's gotchas when harvest notes are written. An unmigrated DB or an uncaught fetch error drops the connection, and the Client proxy answers 502. It is a documentation-only fix and changes nothing in the build.
6. At harvest, map `test_video_handler.py` and extend the `test_videos_worker.py` entry in `.un/skills/devsecops/config.json` to cover `db.ts`, `dist/db.js` and `schema.sql`. Cost: a local config edit. Without it, a change only to `db.ts` never re-runs the worker test.

## 2026-09-27 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft


# Draft implementation: issue 10, video metadata completeness

I read every file this touches before drafting: `video.py`, `whitelist_migrations.py`, `sync-whitelist.py`, `schema.sql`, `db.ts`, `videos-worker.ts`, `video-page.html`, `index.ts`, `video.css`, `test_videos_worker.py`, `test_repair_video_channel_names.py` and `test_internal_events.py`. New code copies each file's own style: one-line docstrings or `/** Handle … */` blocks, the `has_x`/`x_expr` rebuild pattern, `pick_*` helpers, and bulleted test-module docstrings.

The step's ladder placeholder (`{rat_tail_ladder}`) arrived unrendered. This draft is therefore written against R1–R7, the plan and the settled impact inventory.

## What has to be testable (ladder rung 1)

| Claim | Where it is proven |
|---|---|
| Success writes all R2 fields, bumps `last_checked_at`, resets `instances.last_error*`, and returns the R5 keys | `test_video_handler.py::test_success_refreshes_row_and_response` |
| A caught network error (stub `None`, and real `urlopen` raising `URLError`) writes nothing and answers from the DB | `test_fetch_failure_leaves_db_untouched[stub-none, urlopen-urlerror]` |
| A malformed body (not JSON, bad UTF-8, a JSON list) writes nothing | `test_fetch_failure_leaves_db_untouched[not-json, bad-utf8, json-list]` |
| A partial payload keeps the stored tags and category | `test_partial_payload_keeps_tags_and_category` |
| `tags: []` stores `"[]"` and returns `[]` | `test_empty_tag_list_propagates` |
| A source change between two requests is reflected in the DB and the response | `test_second_request_reflects_source_change` |
| Labels: `"15"` gives the label, an unknown id stays raw, a text category passes through, a language code gives its label, an unknown code stays raw | `test_response_labels` (parametrised, DB-only path) |
| The whitelist migration adds `language`, keeps rows and FTS triggers, and is idempotent | `test_migration_adds_language_column` |
| The crawler persists `language` | `test_videos_worker.py::test_crawl_writes_each_hosts_own_channel_name` (extended) |
| The crawler adds `language` to an old crawl.db | `test_videos_worker.py::test_crawl_adds_language_to_existing_db` |

## Module map

| File | Change |
|---|---|
| `engine/server/api/handlers/video.py` | Parse guard, `None` success signal, new extractors, one merge, a write only on success, new response keys |
| `engine/server/data/peertube_labels.py` | **new**: `CATEGORY_LABELS`, `LANGUAGE_LABELS`, `category_label`, `language_label` |
| `engine/server/db/jobs/whitelist_migrations.py` | `migrate_videos_language`; the rebuild carries `language` |
| `engine/server/db/jobs/sync-whitelist.py` | `language TEXT` in `ensure_content_schema` |
| `engine/crawler/schema.sql` | `language TEXT` after `category` (no index) |
| `engine/crawler/src/db.ts` | `migrateVideosLanguage`; the rebuild carries `language`; `VideoUpsertRow.language`; the upsert |
| `engine/crawler/src/videos-worker.ts` | `PeerTubeLanguage`, `extractLanguage`, `toVideoRow.language` |
| `engine/crawler/dist/*.js` | `npm run build`, commit every changed dist file |
| `client/frontend/video-page.html` | `video-taxonomy` block |
| `client/frontend/src/pages/video-page/index.ts` | Type, both fetch paths, `renderTaxonomy` |
| `client/frontend/src/video.css` | Taxonomy and chip styles |
| `client/frontend/dist` | `npm run build`; delete orphaned hashed assets |
| `tests/active/test_video_handler.py` | **new** |
| `tests/active/test_videos_worker.py` | Extended, plus one new case |

Unchanged on purpose: `client/backend/server.py` (it passes the body through), `similar.py`, `updater-worker.py`, `merge-staging-db.py` and `build-video-embeddings.py`.

---

## 1. `engine/server/api/handlers/video.py`

### Imports
```python
from data.time import now_ms
from data.popularity import compute_popularity
from data.peertube_labels import category_label, language_label
from http_utils import respond_json
```

### `fetch_video_row`
The SELECT list gains three lines after `v.nsfw`:
```sql
          v.nsfw,
          v.language,
          v.duration,
          v.thumbnail_url,
          v.last_checked_at,
```

### `fetch_instance_json`
Invariant: it returns a `dict`, or `None`. It never raises for network, HTTP, decode or parse failures. The `# pragma: no cover` comes off because the tests now cover this branch.
```python
def fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:
    """Fetch a JSON object from a PeerTube instance API path; None on network failure, non-200, a malformed body or a non-object body."""
    url = f"https://{host}{path}"
    req = Request(url, headers={"accept": "application/json"})
    try:
        with urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        logging.info("[video] instance request failed: %s", exc)
        return None
    except ValueError as exc:
        # UnicodeDecodeError and JSONDecodeError are both ValueError.
        logging.info("[video] instance response is not valid JSON: host=%s path=%s: %s", host, path, exc)
        return None
    if not isinstance(data, dict):
        logging.info("[video] instance response is not a JSON object: host=%s path=%s", host, path)
        return None
    return data
```

### New and changed helpers (placed next to the existing ones)
```python
def pick_present(value: Any, fallback: Any) -> Any:
    """Return value unless it is None, else fallback (source-over-DB merge rule)."""
    return fallback if value is None else value


def id_text(value: Any) -> str | None:
    """Normalize a PeerTube id to text: a non-empty trimmed string or an int (never a bool); None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return pick_text(value)


def to_tags_json(value: Any) -> str | None:
    """Convert a tag list to a JSON array of its string elements ("[]" when there are none); None when the value is not a list."""
    if isinstance(value, list):
        return json.dumps([tag for tag in value if isinstance(tag, str)], ensure_ascii=False)
    return None


def extract_category(value: Any) -> str | None:
    """Extract the category label/name, else its id as text; a plain string or int is kept as text; None when absent or empty."""
    if isinstance(value, dict):
        return pick_text(value.get("label"), value.get("name")) or id_text(value.get("id"))
    return id_text(value)


def extract_language(value: Any) -> str | None:
    """Extract the PeerTube language code: an object's id or a plain non-empty string; None for a null id or anything else."""
    if isinstance(value, dict):
        return pick_text(value.get("id"))
    return pick_text(value)


def tags_from_json(value: Any) -> list[str]:
    """Parse stored tags_json into its string tags; [] when null, empty, invalid or not a list."""
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [tag for tag in parsed if isinstance(tag, str)]
```

Decisions:
- **`ensure_ascii=False`.** Refreshed tags are stored as raw UTF-8, the same as the crawler's `JSON.stringify`, so FTS indexes the words rather than `\uXXXX` escapes. This resolves the judgment call the `to_tags_json` inventory entry left open.
- **`extract_category` with a plain string.** It now goes through `pick_text`, so `""` or whitespace keeps the DB value (the gap the inventory found).
- **Integer ids only.** Floats and bools are rejected; PeerTube category ids are integers.

### `fetch_instance_video_dynamic`
Invariant: `None` exactly when the detail fetch gave no dict (R1). Otherwise a dict in which `None` always means "keep the DB value".
```python
def fetch_instance_video_dynamic(host: str, video_id: str) -> dict[str, Any] | None:
    """Fetch live video metadata from instance and normalize fields; None when the video detail fetch fails (the single success signal)."""
    detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}")
    if detail is None:
        return None
    account = detail.get("account")
    if not isinstance(account, dict):
        account = {}
    channel = detail.get("channel")
    if not isinstance(channel, dict):
        channel = {}
    channel_slug = pick_text(channel.get("name"))
    # ... channel_display / channel_followers / channel_detail block unchanged ...
    return {
        "title": pick_text(detail.get("name"), detail.get("title")),
        "description": pick_text(detail.get("description")),
        "views": ...,  # unchanged
        "likes": ...,  # unchanged
        "dislikes": ...,  # unchanged
        "tags_json": to_tags_json(detail.get("tags")),
        "category": extract_category(detail.get("category")),
        "language": extract_language(detail.get("language")),
        "nsfw": to_nullable_bool(detail.get("nsfw")),
        "duration": pick_number(detail.get("duration")),
        "thumbnail_url": resolve_asset_url(host, pick_text(detail.get("thumbnailUrl"), detail.get("thumbnailPath"))) or None,
        # channel_slug, channel_display, channel_followers, account_* unchanged
    }
```
The `or None` on `thumbnail_url` is there because `resolve_asset_url` returns `""` for a missing value. Without it, a missing thumbnail would overwrite the stored one with `""`.

### `handle_video_request`: merge, response, write
```python
    instance_domain = row.get("instance_domain") or host_param or ""
    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else None
    # One merged value set feeds both the response and the UPDATE; on failure `source` is empty, so every field is the DB value.
    source = dynamic if dynamic is not None else {}

    title = source.get("title") or row.get("title")
    description = source.get("description") or row.get("description")
    views = pick_present(source.get("views"), row.get("views"))
    likes = pick_present(source.get("likes"), row.get("likes"))
    dislikes = pick_present(source.get("dislikes"), row.get("dislikes"))
    channel_display = source.get("channel_display") or row.get("channel_display_name") or row.get("channel_name")
    channel_slug = source.get("channel_slug") or row.get("channel_slug")
    channel_followers = pick_present(source.get("channel_followers"), row.get("channel_followers_count"))
    tags_json = pick_present(source.get("tags_json"), row.get("tags_json"))
    category = pick_present(source.get("category"), row.get("category"))
    language = pick_present(source.get("language"), row.get("language"))
    nsfw = pick_present(source.get("nsfw"), row.get("nsfw"))
    duration = pick_present(source.get("duration"), row.get("duration"))
    thumbnail_url = pick_present(source.get("thumbnail_url"), row.get("thumbnail_url"))
```
The `channel_url`, `embed_url` and `original_url` code is unchanged.

The response keeps all 18 keys; `"accountAvatarUrl": source.get("account_avatar_url") or ""` replaces `dynamic.get(...)`. Six keys are appended:
```python
        "tags": tags_from_json(tags_json),
        "category": category_label(category),
        "language": language_label(language),
        "nsfw": None if nsfw is None else bool(nsfw),
        "duration": pick_number(duration),
        "thumbnailUrl": thumbnail_url or "",
```

Write block: the guard becomes `if dynamic is not None and instance_domain and row.get("video_id"):` and it tests identity, not truthiness. The UPDATE becomes:
```sql
UPDATE videos
SET title = ?, description = ?, channel_name = ?, views = ?, likes = ?, dislikes = ?,
    popularity = ?,
    tags_json = ?, category = ?, language = ?, nsfw = ?, duration = ?, thumbnail_url = ?, last_checked_at = ?
WHERE video_id = ? AND instance_domain = ?
```
The parameter tuple is extended in the same order: `…, tags_json, category, language, nsfw, duration, thumbnail_url, checked_at, video_id, instance_domain`. The `channels` UPDATE, the `instances` reset, the transaction and the `OperationalError` catch are unchanged.

Invariant: on failure no statement runs, so `last_checked_at`, `channels` and `instances.last_error*` stay exactly as they were.

Pre-existing issue, flagged and not changed: on success with no channel slug anywhere, the `channels` UPDATE writes `channel_name = NULL`.

---

## 2. `engine/server/data/peertube_labels.py` (new)
```python
"""PeerTube default video category and language labels.

Responsibilities:
- Map PeerTube's stock category ids and language codes to display labels for /api/video.
- Leave unknown ids and codes raw (named simplification: plugin-added or renamed entries are not covered; upgrade path is caching each instance's /api/v1/videos/categories and /api/v1/videos/languages).
"""
from __future__ import annotations

CATEGORY_LABELS: dict[str, str] = {
    "1": "Music", "2": "Films", "3": "Vehicles", "4": "Art", "5": "Sports", "6": "Travels", "7": "Gaming", "8": "People", "9": "Comedy",
    "10": "Entertainment", "11": "News & Politics", "12": "How To", "13": "Education", "14": "Activism", "15": "Science & Technology", "16": "Animals", "17": "Kids", "18": "Food",
}

LANGUAGE_LABELS: dict[str, str] = { ... }  # see below


def category_label(value: str | None) -> str:
    """Return the display label for a stored category: a digit-only id resolves through the default map, anything else (or an unknown id) is returned as is; "" when empty."""
    if not isinstance(value, str) or not value:
        return ""
    if value.isascii() and value.isdigit():
        return CATEGORY_LABELS.get(value, value)
    return value


def language_label(value: str | None) -> str:
    """Return the display label for a stored language code (case-sensitive); an unknown code is returned raw; "" when empty."""
    if not isinstance(value, str) or not value:
        return ""
    return LANGUAGE_LABELS.get(value, value)
```

**`LANGUAGE_LABELS` contents.** This is PeerTube's `buildLanguages()` output: living ISO 639-1 languages keyed by their 639-1 code, plus the extra 639-3 set, keyed by the 639-3 code, including the sign languages. The draft literal below was written from memory. Before commit, the implementation step **must replace it wholesale** with the JSON from a stock instance's `GET /api/v1/videos/languages`, pasted as a literal. This is the "copied once" step in the plan, and it removes the fidelity risk rather than accepting it.
```python
LANGUAGE_LABELS: dict[str, str] = {
    "aa": "Afar", "ab": "Abkhazian", "af": "Afrikaans", "ak": "Akan", "am": "Amharic", "an": "Aragonese", "ar": "Arabic", "as": "Assamese", "av": "Avaric", "ay": "Aymara", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bi": "Bislama", "bm": "Bambara", "bn": "Bengali", "bo": "Tibetan", "br": "Breton", "bs": "Bosnian",
    "ca": "Catalan", "ce": "Chechen", "ch": "Chamorro", "co": "Corsican", "cr": "Cree", "cs": "Czech", "cv": "Chuvash", "cy": "Welsh",
    "da": "Danish", "de": "German", "dv": "Dhivehi", "dz": "Dzongkha", "ee": "Ewe", "el": "Greek", "en": "English", "eo": "Esperanto", "es": "Spanish", "et": "Estonian", "eu": "Basque",
    "fa": "Persian", "ff": "Fulah", "fi": "Finnish", "fj": "Fijian", "fo": "Faroese", "fr": "French", "fy": "Western Frisian",
    "ga": "Irish", "gd": "Scottish Gaelic", "gl": "Galician", "gn": "Guarani", "gu": "Gujarati", "gv": "Manx",
    "ha": "Hausa", "he": "Hebrew", "hi": "Hindi", "ho": "Hiri Motu", "hr": "Croatian", "ht": "Haitian", "hu": "Hungarian", "hy": "Armenian", "hz": "Herero",
    "id": "Indonesian", "ig": "Igbo", "ii": "Sichuan Yi", "ik": "Inupiaq", "is": "Icelandic", "it": "Italian", "iu": "Inuktitut",
    "ja": "Japanese", "jv": "Javanese", "ka": "Georgian", "kg": "Kongo", "ki": "Kikuyu", "kj": "Kuanyama", "kk": "Kazakh", "kl": "Kalaallisut", "km": "Central Khmer", "kn": "Kannada", "ko": "Korean", "kr": "Kanuri", "ks": "Kashmiri", "ku": "Kurdish", "kv": "Komi", "kw": "Cornish", "ky": "Kirghiz",
    "la": "Latin", "lb": "Luxembourgish", "lg": "Ganda", "li": "Limburgan", "ln": "Lingala", "lo": "Lao", "lt": "Lithuanian", "lu": "Luba-Katanga", "lv": "Latvian",
    "mg": "Malagasy", "mh": "Marshallese", "mi": "Maori", "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese", "my": "Burmese",
    "na": "Nauru", "nb": "Norwegian Bokmål", "nd": "North Ndebele", "ne": "Nepali", "ng": "Ndonga", "nl": "Dutch", "nn": "Norwegian Nynorsk", "no": "Norwegian", "nr": "South Ndebele", "nv": "Navajo", "ny": "Nyanja",
    "oc": "Occitan", "oj": "Ojibwa", "om": "Oromo", "or": "Oriya", "os": "Ossetian", "pa": "Panjabi", "pl": "Polish", "ps": "Pushto", "pt": "Portuguese", "pt-PT": "Portuguese (Portugal)", "qu": "Quechua",
    "rm": "Romansh", "rn": "Rundi", "ro": "Romanian", "ru": "Russian", "rw": "Kinyarwanda",
    "sc": "Sardinian", "sd": "Sindhi", "se": "Northern Sami", "sg": "Sango", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sm": "Samoan", "sn": "Shona", "so": "Somali", "sq": "Albanian", "sr": "Serbian", "ss": "Swati", "st": "Southern Sotho", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai", "ti": "Tigrinya", "tk": "Turkmen", "tl": "Tagalog", "tn": "Tswana", "to": "Tonga", "tr": "Turkish", "ts": "Tsonga", "tt": "Tatar", "tw": "Twi", "ty": "Tahitian",
    "ug": "Uighur", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "ve": "Venda", "vi": "Vietnamese", "wa": "Walloon", "wo": "Wolof", "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba", "za": "Zhuang",
    "zh": "Chinese", "zh-Hans": "Simplified Chinese", "zh-Hant": "Traditional Chinese", "zu": "Zulu",
    "avk": "Kotava", "jbo": "Lojban", "kab": "Kabyle", "tlh": "Klingon", "tok": "Toki Pona", "zgh": "Standard Moroccan Tamazight",
    "sgn": "Sign Languages", "ase": "American Sign Language", "asq": "Austrian Sign Language", "bfi": "British Sign Language", "bzs": "Brazilian Sign Language", "csl": "Chinese Sign Language", "cse": "Czech Sign Language", "dsl": "Danish Sign Language", "fsl": "French Sign Language", "gsg": "German Sign Language", "jsl": "Japanese Sign Language", "pks": "Pakistan Sign Language", "rsl": "Russian Sign Language", "sdl": "Saudi Arabian Sign Language", "sfb": "Langue des signes de Belgique Francophone", "sfs": "South African Sign Language", "ssp": "Spanish Sign Language", "swl": "Swedish Sign Language", "tsq": "Thai Sign Language",
}
```
The tests assert only `"en"` gives "English" and `"zh-Hans"` gives "Simplified Chinese". The stock list keeps both, so pasting the real list will not break them.

---

## 3. Server whitelist DB

### `whitelist_migrations.py`
```python
def migrate_videos_language(conn: sqlite3.Connection) -> None:
    """Add the nullable `language` column (PeerTube language code) to a videos table that predates it.

    Additive and idempotent: rows, `videos_fts` and its triggers are untouched, since none reference `language`.
    """
    if not _table_exists(conn, "videos"):
        return
    if "language" in _columns(conn, "videos"):
        return
    conn.execute("ALTER TABLE videos ADD COLUMN language TEXT")
```

`migrate_videos_schema` rebuild changes:
- add `has_language = "language" in columns` and `language_expr = "language" if has_language else "NULL"`;
- add `language TEXT,` after `category TEXT,` in `videos_new`;
- add `language,` after `category,` in the INSERT list;
- add `{language_expr},` after `category,` in the SELECT list.

The INSERT and SELECT lists stay positionally aligned.

`migrate_whitelist_schema` then calls, in order:
```python
    migrate_instances_schema(conn, table_name)
    migrate_channels_schema(conn)
    migrate_videos_schema(conn)
    migrate_videos_language(conn)
```

### `sync-whitelist.py`
In `ensure_content_schema`, add `language TEXT,` after `category TEXT,`. Nothing else: `VIDEO_COLUMNS` picks the column up from `schema.sql`.

---

## 4. Crawler

### `schema.sql`
Add `  language TEXT,` after `  category TEXT,`. Do not add an index on it: the first `db.exec(schemaSql)` runs against old tables.

### `db.ts`
```ts
function applyBaseSchema(db: Database.Database) {
  db.exec(schemaSql);
  migrateInstances(db);
  migrateChannels(db);
  migrateVideos(db);
  migrateVideosLanguage(db);
  db.exec(schemaSql);
}

/**
 * Add the videos.language column (PeerTube language code) to a crawl DB that predates it.
 */
function migrateVideosLanguage(db: Database.Database) {
  if (!tableExists(db, "videos")) return;
  if (getColumns(db, "videos").includes("language")) return;
  db.exec("ALTER TABLE videos ADD COLUMN language TEXT");
}
```

`migrateVideos`:
- add `const hasLanguage = columns.includes("language");` and `const languageExpr = hasLanguage ? "language" : "NULL";`;
- add `language TEXT,` after `category TEXT,` in `videos_new`;
- add `language,` after `category,` in the INSERT list;
- add `${languageExpr},` after `category,` in the SELECT list.

`VideoUpsertRow` gains `language: string | null;` after `category`.

`upsertStmt`:
- the INSERT list gains `language,` after `category,`;
- VALUES becomes 26 `?` followed by `NULL, NULL, 0`;
- ON CONFLICT gains `language = excluded.language,` after `category = excluded.category,`.

`upsertVideos` gains `row.language,` directly after `row.category,`.

Alignment check: the column list, the `?` count and the `run()` arguments each gain exactly one entry, in the same slot.

This follows the plan and keeps `language` consistent with `category`: a re-crawl whose payload has `{id: null}` sets crawl.db's `language` to NULL. This is noted in the inventory and stays as is.

### `videos-worker.ts`
```ts
interface PeerTubeLanguage {
  id?: string | null;
  label?: string;
}
```
`PeerTubeVideo` gains `language?: PeerTubeLanguage | string;` after `category`. `toVideoRow` gains `language: extractLanguage(video.language),` after `category:`.
```ts
/**
 * Handle extract language: the PeerTube language code (an object's id or a plain string), trimmed; null otherwise, including a null id.
 */
function extractLanguage(value: PeerTubeVideo["language"]): string | null {
  const raw = value && typeof value === "object" ? value.id : value;
  const code = typeof raw === "string" ? raw.trim() : "";
  return code || null;
}
```
The trim makes this match the handler's `pick_text` exactly: numbers, `""` and whitespace all give `null`.

### Dist
Run `cd engine/crawler && npm install && npm run build`, then commit `dist/db.js`, `dist/videos-worker.js` and any other file tsc rewrites (for example `host-filters.js`). Review the full dist diff.

---

## 5. Video page

### `video-page.html` (between `video-meta-row` and `video-description`)
```html
            <div id="video-taxonomy" class="video-taxonomy" hidden>
              <span id="video-category" class="taxonomy-item" hidden><span class="taxonomy-label">Category</span><span id="video-category-value" class="taxonomy-value"></span></span>
              <span id="video-language" class="taxonomy-item" hidden><span class="taxonomy-label">Language</span><span id="video-language-value" class="taxonomy-value"></span></span>
              <ul id="video-tags" class="video-tags" aria-label="Tags"></ul>
            </div>
```
There are no inline styles, because of the CSP. Elements are hidden with the `hidden` attribute.

### `index.ts`
New element lookups go with the others at the top:
```ts
const taxonomyEl = document.getElementById("video-taxonomy");
const categoryEl = document.getElementById("video-category");
const categoryValueEl = document.getElementById("video-category-value");
const languageEl = document.getElementById("video-language");
const languageValueEl = document.getElementById("video-language-value");
const tagsEl = document.getElementById("video-tags");
```

`VideoMetadata` gains `tags?: string[]; category?: string; language?: string;`.

`fetchVideoMetadataFromServer` return gains:
```ts
      tags: toStringList(data.tags),
      category: typeof data.category === "string" ? data.category : "",
      language: typeof data.language === "string" ? data.language : "",
```

`fetchVideoMetadataFromInstance` return gains:
```ts
      tags: toStringList(data.tags),
      category: peerTubeLabel(data.category, false),
      language: peerTubeLabel(data.language, true),
```

New helpers, placed near `normalizeNumber`:
```ts
/**
 * Handle to string list: the string elements of an array, else [].
 */
function toStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/**
 * Handle PeerTube label: the trimmed `label` of a `{id, label}` object; with requireId, "" when the id is null (PeerTube's unset value).
 */
function peerTubeLabel(value: unknown, requireId: boolean): string {
  if (!value || typeof value !== "object") return "";
  const { id, label } = value as { id?: unknown; label?: unknown };
  if (requireId && (id === null || id === undefined)) return "";
  return typeof label === "string" ? label.trim() : "";
}

/**
 * Handle render taxonomy: category, language and tag chips via textContent only; the whole block is hidden when no metadata resolved.
 */
function renderTaxonomy(metadata: VideoMetadata | null) {
  if (!taxonomyEl) return;
  taxonomyEl.hidden = !metadata;
  if (!metadata) return;
  setTaxonomyItem(categoryEl, categoryValueEl, metadata.category ?? "");
  setTaxonomyItem(languageEl, languageValueEl, metadata.language ?? "");
  if (tagsEl) {
    const tags = metadata.tags ?? [];
    const items = tags.map((tag) => {
      const item = document.createElement("li");
      item.className = "tag-chip";
      item.textContent = tag;
      return item;
    });
    if (items.length === 0) {
      const empty = document.createElement("li");
      empty.className = "video-tags-empty";
      empty.textContent = "No tags";
      items.push(empty);
    }
    tagsEl.replaceChildren(...items);
  }
}

/**
 * Handle set taxonomy item: show the value, or hide the item when it is empty.
 */
function setTaxonomyItem(itemEl: HTMLElement | null, valueEl: HTMLElement | null, value: string) {
  if (valueEl) valueEl.textContent = value;
  if (itemEl) itemEl.hidden = !value;
}
```
`loadVideo` calls `renderTaxonomy(metadata);` directly before the `descriptionEl` block.

Decisions:
- **No metadata at all.** When both fetches fail, the block is hidden: nothing is known, so "No tags" would be a claim the page cannot make.
- **Language.** The instance fallback hides a null-id language, which matches the server path.
- **Category.** "Unknown" shows on both paths, following R2 literally.

### `video.css` (after `.metric svg`)
```css
.video-taxonomy {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.8rem;
  font-size: 0.85rem;
  color: var(--muted);
}

.video-taxonomy[hidden],
.video-taxonomy [hidden] {
  display: none;
}

.taxonomy-item {
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
}

.taxonomy-label {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.taxonomy-value {
  color: var(--accent-strong);
  font-weight: 600;
}

.video-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.tag-chip {
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  background: rgba(180, 87, 55, 0.08);
  color: var(--accent-strong);
  font-size: 0.8rem;
}

.video-tags-empty {
  font-style: italic;
}
```
The explicit `[hidden]` rule is needed because an author `display:` rule overrides the UA default.

### `client/frontend/dist`
Run `npm run build`, commit the new hashed `video-*.js` / `video-*.css` and `dist/video-page.html`, and delete the orphaned `video-gjYm1MC8.js` and `video-ypOuFwNw.css`, plus any re-hashed shared chunk.

---

## 6. Tests

### `tests/active/test_video_handler.py` (new)
Module docstring, in the suite's bullet style:
```text
"""`/api/video` (`handle_video_request`) refreshes the stored video from its source instance only when the video detail fetch returns a JSON object, answers from one merged value set, and maps category and language to PeerTube default labels; `migrate_whitelist_schema` adds `videos.language` to an existing whitelist DB.

- A successful fetch writes the source title, description, stats, tags_json, category, language, nsfw, duration and thumbnail_url, moves last_checked_at forward, clears instances.last_error/_at/_source, and the response carries tags, category, language, nsfw, duration and thumbnailUrl.
- A caught network error (the fetch stub returning None, and the real fetch with urlopen raising URLError) and a malformed body (not JSON, bad UTF-8, a JSON list) leave every videos and channels column and instances.last_error as they were, and the response equals the DB values.
- A payload with stats but no tags or category keeps the stored tags_json and category; `tags: []` stores "[]" and answers `tags: []`.
- A source change between two requests is reflected in the second response and in the DB.
- A stored "15" answers "Science & Technology", "99" answers "99", "Music" answers "Music", "en" answers "English", "zh-Hans" answers "Simplified Chinese", "xx" answers "xx".
- The migration adds `language` to a pre-change videos table, keeps every row and the three FTS triggers, and a second run changes nothing.

The DB schema, triggers included, comes from `sync-whitelist.py`; the instance is never contacted: `fetch_instance_json` or `urlopen` is replaced on `handlers.video`.
"""
```

Setup, following `test_internal_events.py` and `test_repair_video_channel_names.py`:
```python
ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from handlers import video  # noqa: E402

HOST = "peer.example"
OLD_CHECKED_AT = 1_000
VIDEO_PATH = "/api/v1/videos/v1"
CHANNEL_PATH = "/api/v1/video-channels/newslug"
PARAMS = {"id": ["v1"], "host": [HOST]}
SOURCE = {"name": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": {"id": 15, "label": "Science & Technology"}, "language": {"id": "en", "label": "English"}, "nsfw": True, "duration": 321, "thumbnailPath": "/static/thumbnails/new.jpg", "channel": {"name": "newslug", "displayName": "New Chan"}}
```

**Fixtures:**
- `_load_job(name, filename)`, copied from the repair test.
- `sync_job` and `migrations`, module scope, loaded as `sync_whitelist_video_handler` and `whitelist_migrations_video_handler`.
- `server(tmp_path, sync_job)`:
  - opens `sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)` and sets `row_factory = sqlite3.Row`;
  - runs `ensure_whitelist_schema` and `ensure_content_schema`;
  - seeds one `instances` row (`HOST`, `last_error='boom'`, `last_error_at=5`, `last_error_source='video'`);
  - seeds one `channels` row (`'7', HOST, channel_name 'oldslug', display_name 'Old Chan', followers_count 3`);
  - seeds one `videos` row with every column below:

| Column | Value |
|---|---|
| `video_id` | `'v1'` |
| `video_uuid` | `'uuid-1'` |
| `instance_domain` | `HOST` |
| `channel_id` | `'7'` |
| `channel_name` | `'Old Chan'` |
| `title` | `'Old title'` |
| `description` | `'Old desc'` |
| `tags_json` | `'["old"]'` |
| `category` | `'Music'` |
| `language` | `'fr'` |
| `nsfw` | `0` |
| `duration` | `10` |
| `thumbnail_url` | `'https://peer.example/old.jpg'` |
| `views` | `1` |
| `likes` | `1` |
| `dislikes` | `0` |
| `published_at` | `1_600_000_000_000` |
| `last_checked_at` | `OLD_CHECKED_AT` |

  - commits, and returns `SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)`;
  - closes the connection on teardown.
- `responses(monkeypatch)`: patches `video.respond_json` to append `(status, body)` and returns the list.
- `_serve(monkeypatch, payloads: dict[str, dict | None])`: patches `video.fetch_instance_json` with `lambda host, path: payloads.get(path)`.
- `_snapshot(conn)`: returns `SELECT * FROM videos WHERE video_id='v1'`, `SELECT * FROM channels`, and `SELECT last_error, last_error_at, last_error_source FROM instances`, each as a tuple of `tuple(row)`.
- `_FakeResponse(body: bytes)`: `status = 200`, `__enter__` returns self, `__exit__` returns False, and `read()` returns the body.

**Tests:**
- `test_success_refreshes_row_and_response`. It serves `{VIDEO_PATH: SOURCE, CHANNEL_PATH: {"followersCount": 9}}`, calls `video.handle_video_request(None, server, PARAMS)`, and asserts:
  - the DB row's title, description, views, likes, dislikes, tags_json, category, language, nsfw, duration and thumbnail_url equal `("New title", "New desc", 50, 5, 1, '["alpha", "beta"]', "Science & Technology", "en", 1, 321, "https://peer.example/static/thumbnails/new.jpg")`;
  - `last_checked_at > OLD_CHECKED_AT`;
  - `instances.last_error*` are all NULL;
  - the response is status 200 with `tags == ["alpha", "beta"]`, `category == "Science & Technology"`, `language == "English"`, `nsfw is True`, `duration == 321` and `thumbnailUrl` equal to the stored URL;
  - the 18 original keys are all still present.
- `test_fetch_failure_leaves_db_untouched`, parametrised with ids:
  - `stub-none`: `_serve` with `{}`;
  - `urlopen-urlerror`: `monkeypatch.setattr(video, "urlopen", raising URLError("down"))`;
  - `not-json`: `urlopen` returns `_FakeResponse(b"<html>")`;
  - `bad-utf8`: body `b"\xff\xfe"`;
  - `json-list`: body `b"[1, 2]"`.

  It asserts `_snapshot` is equal before and after (every column, `last_checked_at` included, `last_error == 'boom'`) and that the response is status 200 with `title == "Old title"`, `description == "Old desc"`, `views == 1`, `tags == ["old"]`, `category == "Music"`, `language == "French"`, `nsfw is False`, `duration == 10`, `thumbnailUrl == "https://peer.example/old.jpg"` and `channelName == "Old Chan"`.
- `test_partial_payload_keeps_tags_and_category`. It serves `{VIDEO_PATH: {"views": 77}}` and asserts the DB has `views == 77`, `tags_json == '["old"]'`, `category == "Music"` and `language == "fr"`, and the response has `tags == ["old"]` and `category == "Music"`.
- `test_empty_tag_list_propagates`. It serves `{VIDEO_PATH: {"tags": []}}` and asserts the DB has `tags_json == "[]"` and the response has `tags == []`.
- `test_second_request_reflects_source_change`. The first request uses `SOURCE`. The second uses `{**SOURCE, "name": "Renamed", "tags": ["gamma"]}`, with the same `payloads` dict mutated. It asserts the second response has title "Renamed" and tags `["gamma"]`, and the DB has the same values.
- `test_response_labels`, parametrised on `(category, language, expected_category, expected_language)`:
  - `("15", "en", "Science & Technology", "English")`;
  - `("99", "zh-Hans", "99", "Simplified Chinese")`;
  - `("Music", "xx", "Music", "xx")`.

  It UPDATEs the seeded row, serves `{}` (so the answer comes from the DB), and asserts the response labels.
- `test_migration_adds_language_column(tmp_path, sync_job, migrations)`:
  - creates the pre-change `videos` table inline. Its DDL is the whitelist `videos` DDL without `language`, error columns included, so only the additive path runs;
  - then runs `ensure_whitelist_schema` + `ensure_content_schema` (FTS and triggers are created, and `videos` is left as is), and inserts two videos;
  - runs `migrations.migrate_whitelist_schema(conn, "instances")` and asserts:
    - `"language"` is in the `PRAGMA table_info(videos)` names;
    - the `SELECT video_id, title, tags_json, category FROM videos ORDER BY video_id` rows are unchanged, and `language` is NULL for both;
    - `SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'videos_fts_%'` equals 3;
    - a second run leaves the `PRAGMA table_info(videos)` output identical.

### `tests/active/test_videos_worker.py`
- Extract the body of the existing test into `_crawl(tmp_path, schema_sql: str, alpha_videos: list[dict]) -> tuple[Path, str, str, str, str, CompletedProcess]`. It holds the node, dist and git asserts, the two stand-ins, the seeding through `conn.executescript(schema_sql)` and the node run.
- Existing test: alpha videos gain `"language": {"id": "en", "label": "English"}` (a-1) and `"language": {"id": None, "label": "Unknown"}` (a-2). It additionally asserts `SELECT video_id, language FROM videos` gives `{"a-1": "en", "a-2": None, "b-1": None}`.
- New `test_crawl_adds_language_to_existing_db`:
  - `legacy = SCHEMA.read_text(encoding="utf-8").replace("  language TEXT,\n", "")`, and it asserts `legacy != SCHEMA.read_text(...)` so the fixture really lacks the column;
  - runs `_crawl` with alpha `[{"uuid": "a-1", "name": "A one", "language": "de"}]`;
  - asserts `"language" in PRAGMA table_info(videos)` names and that a-1's `language == "de"`.
- The docstring gains two bullets:
  - "Each video's `language` is the PeerTube language id, NULL for a null id or no language."
  - "A crawl.db created before `language` existed gains the column when the crawler opens it, and the crawl fills it."

### Harvest-time (not in this worktree's code)
- In `.un/skills/devsecops/config.json` `test_groups`, map the new test to `video.py`, `peertube_labels.py`, `whitelist_migrations.py` and `sync-whitelist.py`.
- Extend `test_videos_worker.py`'s group with `src/db.ts`, `dist/db.js` and `schema.sql`.
- The documentation checklist is settled and carried separately.

---

## Check against plan and requirements (ladder rung 2)

### Pass 1
**R1**
- `fetch_instance_video_dynamic` returning `None` is the only success signal, and the guard is `dynamic is not None`.
- Parse and non-dict failures return `None`; the kept exceptions and the non-200 case are unchanged.
- A channel-detail failure still falls back.
- A failure runs no statement at all.

**R2**
- Every field uses a present-and-valid-or-DB rule, and `thumbnail_url` maps `""` to `None`.
- `"[]"` propagates.
- `extract_category` handles an id-only category, and a blank string keeps the DB value.
- `language` holds the code, and a null id keeps the DB value.
- There is one UPDATE path.

**R3**
- `schema.sql`, the `db.ts` ALTER, the rebuild and the upsert, `videos-worker.ts`, sync, the whitelist migration and its rebuild, `fetch_video_row` and the dist rebuild are all covered.

**R4**
- There is a stdlib map. The category lookup is digit-only, and unknown values stay raw.
- The simplification is named in the module docstring.

**R5**
- There are six new keys with the specified types, and the 18 old keys are kept.
- The proxy is untouched.

**R6**
- There is a block with hidden-when-empty category and language and a "No tags" state.
- Both fetch paths fill it, and everything is set through `textContent` / `createElement`.
- The CSS is compact and there are no inline styles.
- The dist is rebuilt.

**R7**
- Every listed fixture maps to a test in the table at the top.
- The failure assertions use full-row `SELECT *` snapshots.
- The DB comes from the production schema helpers, and nothing touches the network.

### Pass 1 findings, fixed in place
- **Language rule divergence.** TS `toNullableString` does not trim, while Python `pick_text` does, so the two producers could store different values. `extractLanguage` now trims.
- **Destructive migration path.** The legacy table in the migration test would otherwise have gone down the destructive rebuild path. It is now built with the error columns present.

### Pass 2
Nothing unmet.

The simplifications, all named:
- default-only labels (R4);
- a whitespace-only language id is treated as absent on both producers;
- the draft `LANGUAGE_LABELS` literal is marked for wholesale replacement from a stock instance before commit.

## 2026-09-27 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - language column in both producers [code]

**Files touched.** engine/crawler/schema.sql (EDITED), engine/crawler/src/db.ts (EDITED), engine/crawler/src/videos-worker.ts (EDITED), engine/crawler/dist/db.js (EDITED), engine/crawler/dist/videos-worker.js (EDITED), engine/server/db/jobs/whitelist_migrations.py (EDITED), engine/server/db/jobs/sync-whitelist.py (EDITED), tests/active/test_video_handler.py (NEW), tests/active/test_videos_worker.py (EDITED)

**Checkpoint.** Two seams, each following an existing harness. (a) New `tests/active/test_video_handler.py::test_migration_adds_language_column`: it loads `sync-whitelist.py` and `whitelist_migrations.py` with `spec_from_file_location` (precedent: `test_repair_video_channel_names.py`) and builds the pre-change `videos` table inline in a tmp_path DB, error columns included and `language` left out. It runs `ensure_whitelist_schema` + `ensure_content_schema`, inserts two videos, and calls `migrate_whitelist_schema(conn, "instances")`. It then asserts that `language` is among the `PRAGMA table_info(videos)` names, that the `(video_id, title, tags_json, category)` rows are unchanged with `language` NULL, that 3 `videos_fts_%` triggers exist, and that a second run leaves `table_info` identical. (b) `tests/active/test_videos_worker.py`, which runs the committed `dist/videos-worker.js` under node against local PeerTube stand-ins, keeping its stale-dist and missing-tool guards. The existing case gains `language` on the alpha videos and asserts `{a-1: "en", a-2: None, b-1: None}`. The new `test_crawl_adds_language_to_existing_db` seeds crawl.db from `schema.sql` with the `language` line removed (asserting the text really differs) and asserts that the column exists after the crawl and that a-1 has `language == "de"`.

**Intent.** Every videos table the build touches has a nullable `language` column: `whitelist_migrations.migrate_whitelist_schema` adds it to an existing whitelist DB without losing rows or FTS triggers, and the crawler (`schema.sql`, `db.ts`, `videos-worker.ts`) stores each video's PeerTube language code in crawl.db, adding the column to a crawl.db that predates it.

- C1 - `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing.
- C2 - A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed.

**Outcome.** _pending_

#### Phase 2 - default display labels in /api/video [code]

**Files touched.** engine/server/data/peertube_labels.py (NEW), engine/server/api/handlers/video.py (EDITED), tests/active/test_video_handler.py (EDITED)

**Checkpoint.** `tests/active/test_video_handler.py::test_response_labels`, parametrised on `("15","en")`, `("99","zh-Hans")` and `("Music","xx")`. The seam is `handlers.video.handle_video_request(None, server, params)`, imported with `engine/server` and `engine/server/api` on `sys.path` (precedent: `test_internal_events.py`). `server` is a `SimpleNamespace(db, db_lock, video_error_threshold, popularity_like_weight)` over a tmp_path DB built from `sync-whitelist.py`'s `ensure_whitelist_schema` + `ensure_content_schema` and seeded with one instance, one channel and one video. `video.respond_json` is monkeypatched to capture `(status, body)`, and `video.fetch_instance_json` is stubbed to return None, so the answer comes from the DB. The test UPDATEs the seeded row's category and language, then asserts that the response's `category` and `language` equal "Science & Technology"/"English", "99"/"Simplified Chinese" and "Music"/"xx", and that the stored values are still the raw id and code.

**Intent.** The `/api/video` response built by `handle_video_request` carries `category` and `language` as PeerTube default display labels from the new `engine/server/data/peertube_labels.py`, while the stored values stay ids and codes.

- C1 - A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored.
- C2 - A stored language code is answered with its PeerTube default label, and an unknown code is answered raw.

**Outcome.** _pending_

#### Phase 3 - refresh only on success, one merge [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), tests/active/test_video_handler.py (EDITED)

**Checkpoint.** This uses the same `handle_video_request` harness as phase 2, in `tests/active/test_video_handler.py`. Failure seam: `test_fetch_failure_leaves_db_untouched` is parametrised as `stub-none` (`fetch_instance_json` returns None), `urlopen-urlerror`, `not-json`, `bad-utf8` and `json-list`. The last four replace `video.urlopen` with a raiser or a `_FakeResponse`, so the real parse guard in `fetch_instance_json` runs. The test asserts that the `SELECT *` snapshots of the videos row, all channels rows and `instances.last_error*` are equal before and after, and that the status-200 response carries the DB values (title, description, views, tags ["old"], category "Music", language "French", nsfw False, duration 10, thumbnailUrl, channelName). Success seam: a path-keyed `fetch_instance_json` stub drives four tests. `test_success_refreshes_row_and_response` checks that every refreshed column is stored, that `last_checked_at` moved forward, that `instances.last_error*` is NULL, and that the response's new keys equal the stored values while the 18 original keys remain. `test_partial_payload_keeps_tags_and_category` checks that views update while the stored tags_json, category and language stay. `test_empty_tag_list_propagates` checks that "[]" is stored and `[]` is answered. `test_second_request_reflects_source_change` checks that the second response and the DB carry the renamed title and the new tags.

**Intent.** `handle_video_request` in `engine/server/api/handlers/video.py` writes to the DB only when the video detail fetch returns a JSON object, and on success it stores and answers one merged source-over-DB value set, including tags, category, language, nsfw, duration and thumbnail.

- C1 - A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values.
- C2 - A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values.

**Outcome.** _pending_

#### Phase 4 - taxonomy block on the video page [code]

**Files touched.** client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/src/video.css (EDITED), client/frontend/dist (EDITED, rebuilt; orphaned hashed video assets deleted), tests/active/test_frontend_video_taxonomy.py (NEW)

**Checkpoint.** New `tests/active/test_frontend_video_taxonomy.py`, following the esbuild-bundle + node-runner precedent of `test_frontend_videos.py` / `test_frontend_blocks.py`. It bundles `client/frontend/src/pages/video-page/index.ts` with `client/frontend/node_modules/.bin/esbuild` (`--platform=node`, with a CSS loader or empty stub for `video.css`). A runner stubs the platform node lacks: a `document` whose `getElementById` returns a recorded stub element per id, with `createElement` and `replaceChildren`; `window.location.search` carrying `id` and `host`; `localStorage`/`sessionStorage`; and `fetch`, which returns a fixture body for `/api/video` and empty payloads elsewhere. After `loadVideo` settles, the runner reports the `textContent` and `hidden` of `video-category`, `video-category-value`, `video-language`, `video-language-value` and the `video-tags` children. Case 1 uses a body with category "Science & Technology", language "English" and tags ["alpha","beta"], and asserts the two values are visible and there is one `tag-chip` per tag with the tag as its text. Case 2 uses a body with category "", language "" and tags [], and asserts the category and language items are hidden and the only tag child reads "No tags".

**Intent.** The video page (`video-page.html`, `pages/video-page/index.ts`, `video.css`) has a `video-taxonomy` block that shows the category, language and tags from `/api/video` as text only.

- C1 - For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag.
- C2 - For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads "No tags".

**Outcome.** _pending_


Needs coordination: Phase 1 needs `cd engine/crawler && npm install && npm run build` so the committed dist is current; otherwise `test_videos_worker.py` fails on a stale dist. Phase 2 needs a manual step: `LANGUAGE_LABELS` must be replaced wholesale with the JSON from a stock PeerTube instance's `GET /api/v1/videos/languages` (a live endpoint), as the settled draft requires; the checkpoint only asserts "en", "zh-Hans" and unknown codes, so it cannot catch a bad transcription. Phase 4 needs `client/frontend/node_modules` (esbuild) installed and `npm run build` for the committed dist. Deployment (after the merge, not a checkpoint): run the crawler once and `migrate-whitelist.py` on every whitelist.db before restarting the Engine.

Rationale: The step's {principles}, {shape_ladder-ladder} and {tdd_seams} placeholders arrived unrendered, so each seam is taken from an existing harness in tests/active rather than from those texts. The split follows dependency order and one seam per phase. Phase 1 is the schema in both producers: `fetch_video_row` will select `v.language`, so the handler phases cannot start before the column exists in the whitelist schema that their fixture builds, and the crawler half belongs here because it is the same column fact, checked through its own node harness. Phase 2 (labels) lands before phase 3 (the refresh gate) so phase 3's failure test can assert the DB answer in its final labelled form ("French") and nothing has to be rewritten later. The labels are also a separable concern: a pure display lookup exercised through the DB-only response path. Phase 3 holds the R1/R2/R5 core as two clauses, failure writes nothing and success writes and answers one merge. The partial-payload, empty-tags and second-request cases are instances of the merge clause, not separate facts. Phase 4 is the page: the settled draft had no test for R6, so the operator approved a new node/esbuild page-render checkpoint on the `test_frontend_videos.py` precedent. The instance-direct fallback path (`fetchVideoMetadataFromInstance`) is deliberately not checkpointed and was accepted as proposed. There is no prose phase, because the only prose (DATA_BUILD.md runbook order, harvest notes, the devsecops test_groups mapping) is documentation or harvest-time config, which Step 9 handles.

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Every videos table the build touches has a nullable `language` column: `whitelist_migrations.migrate_whitelist_schema` adds it to an existing whitelist DB without losing rows or FTS triggers, and the crawler (`schema.sql`, `db.ts`, `videos-worker.ts`) stores each video's PeerTube language code in crawl.db, adding the column to a crawl.db that predates it.

- C1 - `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing.
- C2 - A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed.

must_prove:
- C1 - `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB, keeps every row and the three FTS triggers, and a second run changes nothing.
- C2 - A crawl stores each video's PeerTube language code in crawl.db (NULL for a null id), including in a crawl.db created before the column existed.

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase1.py:115-116: after `migrate_whitelist_schema(conn, "instances")` on the pre-change whitelist.db, `PRAGMA table_info(videos)` has exactly one `language` row, and its notnull flag is 0 - expected: One `language` row with notnull 0. A probe using a plain `ALTER TABLE videos ADD COLUMN language TEXT` gave `(31, 'language', 'TEXT', 0, None, 0)`. Today's migration adds nothing, and the run fails at :115 with `assert 0 == 1`. - excludes: The migration is left as it is today, or only `ensure_content_schema`'s CREATE TABLE is updated, so an existing DB never gets the column: len(language) == 0. If it is added as `language TEXT NOT NULL DEFAULT ''`, notnull reads 1.
- C1 - tests/tmp/test_10_video_metadata_completeness_phase1.py:117: `SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id` after the first migration - expected: [("v1", "Alpine walk", '["hike"]', "Travels", None), ("v2", "Harbour night", None, None, None)]. The probe printed exactly these two rows after adding the column. - excludes: A rebuild migration (create videos_new, copy, drop, rename) whose column list leaves out tags_json/category, or that forgets the INSERT ... SELECT, reads back NULL tags/category or [] rows. A column added with a default such as 'und' reads 'und' where None is expected.
- C1 - tests/tmp/test_10_video_metadata_completeness_phase1.py:119-122: after the migration, the three `videos_fts_*` triggers are still in sqlite_master; `title : "Alpine"` MATCH returns {"v1"}; a row inserted afterwards with `language='fr'` is found by `title : "Lantern"` as {"v3"} - expected: [("videos_fts_ad",), ("videos_fts_ai",), ("videos_fts_au",)], {"v1"} and {"v3"}. The probe printed all three after adding the column. - excludes: A table-rebuild migration that drops `videos` and takes the triggers with it (reads []). Or one that changes rowids so the external-content index no longer joins (the Alpine MATCH reads set()). Or one that leaves the ai trigger missing (the Lantern MATCH reads set()).
- C1 - tests/tmp/test_10_video_metadata_completeness_phase1.py:128-130: a second `migrate_whitelist_schema` leaves `table_info`, the rows (including v3's 'fr') and the trigger list identical to the state after the first run. That first state is pinned to literals at :115-122. - expected: Identical to the first run's state. The probe got `duplicate column name: language` from a second unguarded ALTER, so any guard has to be real. - excludes: An unguarded ALTER TABLE raises OperationalError "duplicate column name: language" on the second run. A migration that rebuilds on every run drops and recreates the triggers or rewrites the rows, which differ if the rebuild loses the 'fr' value or a column.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase1.py:224: after the committed dist/videos-worker.js crawls two stand-in channels, crawl.db's {video_id: language} is exactly {"a-1": "en", "a-2": None, "b-1": None} - expected: {"a-1": "en", "a-2": None, "b-1": None}. The run showed the crawl reaching both stand-ins and storing all three videos ("finished new_total=3"). It stops at the supporting column check at :220 because crawl.db has no language column yet. - excludes: Not writing language at all: the column is missing or all three values are None. Storing `language.label` gives "English". Storing `JSON.stringify(language)` gives '{"id":"en",...}'. `String(language?.id)` stores "null"/"undefined" for a-2/b-1. Crashing on a video with no `language` drops b-1.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase1.py:256: on a crawl.db built from schema.sql with any language line stripped (control at :246 confirms the column is absent), the crawl leaves videos.language present - expected: "language" in the column names. The run failed here with `assert 'language' in [...]` after "finished new_total=1", so the crawl ran and the column is what's missing. - excludes: Adding `language TEXT` only to schema.sql's CREATE TABLE IF NOT EXISTS, with no migration in db.ts: an existing crawl.db never gets the column, and the upsert naming it would fail or the column stays missing.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase1.py:260: `SELECT video_id, title, language FROM videos ORDER BY video_id` after the crawl over that pre-change crawl.db - expected: [("a-0", "Old one", None), ("a-1", "A one", "de")]. The probe on today's code gave rows [('a-0', 'Old one'), ('a-1', 'A one'), ...]: the unserved a-0 survives and a-1's title is overwritten by the upsert. So the harness reaches the conflict path. - excludes: A migration that recreates the videos table loses a-0 (reads only [("a-1", ...)]). An upsert whose ON CONFLICT DO UPDATE SET list leaves out language keeps a-1's language None ("A one", None) even though the insert values carry "de".

<assertions>
tests/tmp/test_10_video_metadata_completeness_phase1.py:115 - after `migrate_whitelist_schema(conn, "instances")` on a pre-change whitelist videos table (error columns present, language absent; control at :108 checks it is absent), `PRAGMA table_info(videos)` has exactly one `language` column - C1. Wrong implementation (today's migration, which does nothing here): 0 matches.
tests/tmp/test_10_video_metadata_completeness_phase1.py:116 - that column's notnull flag is 0, so the column is nullable - C1
tests/tmp/test_10_video_metadata_completeness_phase1.py:117 - rows `(video_id, title, tags_json, category, language)` read back as `[("v1","Alpine walk",'["hike"]',"Travels",None), ("v2","Harbour night",None,None,None)]`, which are literal seeds and not recomputed - C1. Wrong implementation: a column that is missing raises "no such column", and a lossy rebuild changes the rows.
tests/tmp/test_10_video_metadata_completeness_phase1.py:119 - the `videos_fts_%` triggers are exactly ad/ai/au - C1. Wrong implementation: extending the `migrate_videos_schema` rebuild to cover language drops all three.
tests/tmp/test_10_video_metadata_completeness_phase1.py:120 - `videos_fts` MATCH `title:"Alpine"` still resolves to v1 after the migration - C1
tests/tmp/test_10_video_metadata_completeness_phase1.py:122 - a row inserted after the migration (v3, language 'fr') is found by MATCH `title:"Lantern"`, so the insert trigger still feeds the index on the migrated table - C1
tests/tmp/test_10_video_metadata_completeness_phase1.py:128 - a second `migrate_whitelist_schema` call leaves `table_info(videos)` identical - C1. Wrong implementation: an unconditional ALTER raises "duplicate column name: language".
tests/tmp/test_10_video_metadata_completeness_phase1.py:129 - the second run also leaves the rows identical - C1
tests/tmp/test_10_video_metadata_completeness_phase1.py:130 - the second run also leaves the three triggers in place - C1
tests/tmp/test_10_video_metadata_completeness_phase1.py:223 - the committed dist crawls two stand-ins and stores `{a-1: "en", a-2: None, b-1: None}`: a language id, `{"id": null}` stored as NULL, and a video with no language key stored as NULL - C2. Wrong implementations: storing the label gives "English"/"Unknown", ignoring language gives all None, and a column missing from schema.sql raises "no such column".
tests/tmp/test_10_video_metadata_completeness_phase1.py:254 - on a crawl.db seeded from schema.sql with exactly one `language` line stripped (control at :235 checks `removed == 1`, and the control at :247 checks the column is absent before the crawl), `videos.language` exists after the crawl - C2. Wrong implementation: db.ts without a migration means the upsert error is swallowed per channel, node still exits 0, and the column is missing.
tests/tmp/test_10_video_metadata_completeness_phase1.py:258 - rows read back as `[("a-0","Old one",None), ("a-1","A one","de")]`: a-0, which was not revisited, survives with NULL, and a-1, which already existed, gets "de" through the upsert's ON CONFLICT path - C2. Wrong implementation: language added to the INSERT but left out of `DO UPDATE SET` leaves a-1 NULL.
</assertions>

<probes>
tests/tmp/probe_10_language.py (ValidateTests ["tests/tmp/probe_10_language.py","-s"]): I loaded sync-whitelist.py and whitelist_migrations.py by spec_from_file_location, created the inline pre-change videos table, then ran ensure_whitelist_schema and ensure_content_schema. It printed the columns ending `...invalid_reason, invalid_at` with no language, and the triggers `[('videos_fts_ad',), ('videos_fts_ai',), ('videos_fts_au',)]`. After today's migrate_whitelist_schema, `"language" in columns` printed False, so the check is red now. I then simulated a correct fix with `ALTER TABLE videos ADD COLUMN language TEXT`: table_info showed `(31, 'language', 'TEXT', 0, None, 0)` (notnull at index 3 is 0), the triggers were unchanged, MATCH 'title : "Alpine"' returned `[('v1',)]`, and v3 inserted after the ALTER matched 'title : "Lantern"' as `[('v3',)]`. The rows were `[('v1','Alpine walk','["hike"]','Travels',None), ('v2','Harbour night',None,None,None), ...]`, and a second ALTER raised `duplicate column name: language`. `re.subn(r"^[ \t]*language\b[^\n]*\n", "", "  preview_path TEXT,\n  language TEXT,\n  last_checked_at ...")` returned count 1 with the line removed. node is v22.22.2 and git is at /usr/bin/git; the dist holds db.js and videos-worker.js; `git status --porcelain -- engine/crawler` was empty.
tests/tmp/probe_10_crawl.py (ValidateTests ["tests/tmp/probe_10_crawl.py","-s"]): I ran the current dist/videos-worker.js under node against one stand-in serving a-1 (language de) and a-2 (language id null), with crawl.db seeded from today's schema.sql plus old rows a-0 "Old one" and a-1 "Stale title". It printed rc 0 and `[videos] channel done .../alpha new=2 total=2`. The columns had no language, and the rows were `[('a-0','Old one'), ('a-1','A one'), ('a-2','A two')]`: the unrevisited row survives, and the existing a-1 is overwritten through ON CONFLICT. Today's dist ignores the language field.
Both probe files are still in tests/tmp/ (probe_10_language.py and probe_10_crawl.py) because I have no tool to delete files. Their names do not match pytest's default test_*.py pattern, so a suite run does not collect them; please delete them. I did not run the checkpoint itself so that the workflow's gating run stays the one on record.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_video_metadata_completeness_phase1.py` - 13313 characters, inlined in full

```
"""Every videos table this build touches gains a nullable `language` column holding the PeerTube language code.

- On a whitelist.db whose `videos` table predates `language` (error columns present, FTS index and its three triggers in place, two rows seeded), `migrate_whitelist_schema(conn, "instances")` adds a nullable `language` column; the rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL, the three `videos_fts_*` triggers still exist, a title MATCH still finds the preserved row and a row inserted afterwards, and a second run leaves `table_info`, the rows and the triggers identical.
- The committed `dist/videos-worker.js`, run under node against local PeerTube stand-ins, stores `language.id` per video: "en" for a video carrying it, NULL for `{"id": null}`, NULL for a video with no `language`.
- On a crawl.db seeded from `schema.sql` with its one `language` line removed (so the table really lacks the column) and holding two videos, the crawl adds the column, keeps the video it did not revisit with `language` NULL, and stores "de" on the one it did.
- A missing node or git, a missing or stale dist, or a nonzero node exit fails the test rather than skipping it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWLER_DIR = ROOT / "engine" / "crawler"
SCHEMA = CRAWLER_DIR / "schema.sql"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
# (source, compiled) pairs the crawl runs through: the worker, and the store that migrates crawl.db and writes the rows.
BUILD_PAIRS = [(CRAWLER_DIR / "src" / "videos-worker.ts", DIST), (CRAWLER_DIR / "src" / "db.ts", CRAWLER_DIR / "dist" / "db.js")]
BUILD_HINT = "cd engine/crawler && npm install && npm run build"

# The whitelist videos table as `ensure_content_schema` created it before this build: error columns present, `language` absent.
PRE_CHANGE_VIDEOS_SQL = """
CREATE TABLE videos (
  video_id TEXT NOT NULL,
  video_uuid TEXT,
  video_numeric_id INTEGER,
  instance_domain TEXT NOT NULL,
  channel_id TEXT,
  channel_name TEXT,
  channel_url TEXT,
  account_name TEXT,
  account_url TEXT,
  title TEXT,
  description TEXT,
  tags_json TEXT,
  category TEXT,
  published_at INTEGER,
  video_url TEXT,
  duration INTEGER,
  thumbnail_url TEXT,
  embed_path TEXT,
  views INTEGER,
  likes INTEGER,
  dislikes INTEGER,
  comments_count INTEGER,
  nsfw INTEGER,
  preview_path TEXT,
  popularity REAL NOT NULL DEFAULT 0,
  last_checked_at INTEGER NOT NULL,
  last_error TEXT,
  last_error_at INTEGER,
  error_count INTEGER NOT NULL DEFAULT 0,
  invalid_reason TEXT,
  invalid_at INTEGER,
  PRIMARY KEY (video_id, instance_domain)
);
"""
TRIGGERS_SQL = "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'videos_fts_%' ORDER BY name"
EXPECTED_TRIGGERS = [("videos_fts_ad",), ("videos_fts_ai",), ("videos_fts_au",)]
ROWS_SQL = "SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id"
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"
LANGUAGE_LINE = r"^[ \t]*language\b[^\n]*\n"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_info(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA table_info(videos)").fetchall()


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in _table_info(conn)]


def _matches(conn: sqlite3.Connection, word: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'title : "{word}"',))}


def test_migration_adds_language_column(tmp_path):
    sync_job = _load_job("sync_whitelist_language", "sync-whitelist.py")
    migrations = _load_job("whitelist_migrations_language", "whitelist_migrations.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        conn.executescript(PRE_CHANGE_VIDEOS_SQL)
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.executemany("INSERT INTO videos (video_id, instance_domain, title, tags_json, category, last_checked_at) VALUES (?, 'a.example', ?, ?, ?, 1)", [("v1", "Alpine walk", '["hike"]', "Travels"), ("v2", "Harbour night", None, None)])
        conn.commit()
        assert "language" not in _column_names(conn), "the pre-change videos table already has language"
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS, "the FTS triggers were not in place before the migration"

        migrations.migrate_whitelist_schema(conn, "instances")

        language = [row for row in _table_info(conn) if row[1] == "language"]
        assert len(language) == 1  # C1
        assert language[0][3] == 0, "language is NOT NULL"  # C1
        assert conn.execute(ROWS_SQL).fetchall() == [("v1", "Alpine walk", '["hike"]', "Travels", None), ("v2", "Harbour night", None, None, None)]  # C1
        # A rebuild of `videos` takes the triggers and the external-content index down with it.
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS  # C1
        assert _matches(conn, "Alpine") == {"v1"}  # C1
        conn.execute("INSERT INTO videos (video_id, instance_domain, title, last_checked_at, language) VALUES ('v3', 'a.example', 'Lantern festival', 1, 'fr')")
        assert _matches(conn, "Lantern") == {"v3"}, "the insert trigger no longer feeds videos_fts"  # C1
        conn.commit()

        info_after_first = _table_info(conn)
        rows_after_first = conn.execute(ROWS_SQL).fetchall()
        migrations.migrate_whitelist_schema(conn, "instances")
        assert _table_info(conn) == info_after_first  # C1
        assert conn.execute(ROWS_SQL).fetchall() == rows_after_first  # C1
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS  # C1
    finally:
        conn.close()


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str, src: Path, dist: Path) -> bool:
    """Whether dist predates src: by commit time when both are committed and clean, since a checkout sets mtimes arbitrarily; otherwise by time on disk."""
    dirty = _git(git, "status", "--porcelain", "--", str(src), str(dist))
    src_committed = _git(git, "log", "-1", "--format=%ct", "--", str(src))
    dist_committed = _git(git, "log", "-1", "--format=%ct", "--", str(dist))
    if dirty or not src_committed or not dist_committed:
        return src.stat().st_mtime > dist.stat().st_mtime
    return int(src_committed) > int(dist_committed)


def _require_built_crawler() -> str:
    node = shutil.which("node")
    assert node is not None, f"node is not on PATH; install Node.js, then {BUILD_HINT}"
    git = shutil.which("git")
    assert git is not None, "git is not on PATH, so whether the dist predates its source cannot be told"
    for src, dist in BUILD_PAIRS:
        assert dist.is_file(), f"{dist} is missing; {BUILD_HINT}"
        assert not _dist_is_stale(git, src, dist), f"{dist} predates {src}; {BUILD_HINT}"
    return node


def _instance(slug: str, videos: list[dict]) -> ThreadingHTTPServer:
    """A PeerTube stand-in serving one channel's videos page."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] != f"/api/v1/video-channels/{slug}/videos":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"total": len(videos), "data": videos}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _crawl(node: str, db_path: Path) -> subprocess.CompletedProcess:
    # maxRetries 0 keeps the crawler's https-first attempt against these plain-http servers to one fast failure before its http fallback.
    options = {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
    return subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})


def _stop(*servers: ThreadingHTTPServer) -> None:
    for server in servers:
        server.shutdown()
        server.server_close()


def test_crawl_stores_each_videos_language(tmp_path):
    node = _require_built_crawler()
    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one", "language": {"id": "en", "label": "English"}}, {"uuid": "a-2", "name": "A two", "language": {"id": None, "label": "Unknown"}}])
    beta = _instance("beta", [{"uuid": "b-1", "name": "B one"}])
    try:
        host_a = f"127.0.0.1:{alpha.server_address[1]}"
        host_b = f"127.0.0.1:{beta.server_address[1]}"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executemany("INSERT INTO instances (host) VALUES (?)", [(host_a,), (host_b,)])
            conn.executemany("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES (?, ?, ?, ?, ?, ?)", [("7", "alpha", f"http://{host_a}/video-channels/alpha", "Alpha Display", host_a, 2), ("7", "beta", f"http://{host_b}/video-channels/beta", "Beta Display", host_b, 1)])
            conn.commit()
        finally:
            conn.close()
        proc = _crawl(node, db_path)
    finally:
        _stop(alpha, beta)
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        languages = {video_id: language for video_id, language in conn.execute("SELECT video_id, language FROM videos")}
    finally:
        conn.close()
    assert languages == {"a-1": "en", "a-2": None, "b-1": None}, f"crawl log: {proc.stdout}"  # C2


def test_crawl_adds_language_to_existing_db(tmp_path):
    node = _require_built_crawler()
    schema = SCHEMA.read_text(encoding="utf-8")
    old_schema, removed = re.subn(LANGUAGE_LINE, "", schema, flags=re.M)
    assert removed == 1, f"{SCHEMA} does not carry exactly one language line to strip, so no pre-change crawl.db can be built from it"

    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one", "language": {"id": "de", "label": "German"}}])
    try:
        host = f"127.0.0.1:{alpha.server_address[1]}"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(old_schema)
            conn.execute("INSERT INTO instances (host) VALUES (?)", (host,))
            conn.execute("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES ('7', 'alpha', ?, 'Alpha Display', ?, 1)", (f"http://{host}/video-channels/alpha", host))
            # a-0 is not served, so it only survives if the column is added without dropping rows; a-1 is served, so its language arrives through the upsert's conflict path.
            conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES (?, ?, '7', ?, 1)", [("a-0", host, "Old one"), ("a-1", host, "Stale title")])
            conn.commit()
            assert "language" not in _column_names(conn), "the stripped schema still created videos.language"
        finally:
            conn.close()
        proc = _crawl(node, db_path)
    finally:
        _stop(alpha)
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        assert "language" in _column_names(conn), f"crawl log: {proc.stdout}"  # C2
        rows = conn.execute("SELECT video_id, title, language FROM videos ORDER BY video_id").fetchall()
    finally:
        conn.close()
    assert rows == [("a-0", "Old one", None), ("a-1", "A one", "de")], f"crawl log: {proc.stdout}"  # C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - red (audit round 1)

`tests/tmp/test_10_video_metadata_completeness_phase1.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase1.py  3 failed                               0.0s
  -------------------------------------------------------
  total                                                    3 failed                               1.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 2 UNCARRIED clause(s) - D1b, D8b

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
`test_migration_adds_language_column` fails at line 115 on `assert len(language) == 1` because the `language` list is empty: `migrate_whitelist_schema` → `migrate_videos_schema` does not add the column yet. `test_crawl_stores_each_videos_language` fails at line 220 on `assert "language" in _column_names(conn)`, because neither `schema.sql` nor `dist/db.js` creates or adds `videos.language` yet. `test_crawl_adds_language_to_existing_db` fails at line 256 on the same membership check. In the second and third tests, the staleness assertion at line 158 fires first if the dist is found older than its source.

NOT ASSESSED
1. `src/videos-worker.ts`, `src/db.ts`, `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` were not read in full. I answered the stub question from the assertion form and from grepping the dist and `schema.sql`, which contain no `language` column yet.
2. No `fixtures_path` was supplied. None is needed: the test uses only pytest's built-in `tmp_path` and builds everything else inline.
3. Whether node and git are installed, and whether the dists are older than their sources, can only be settled by running the test. So line 158 may fail before lines 220/256 in the second and third tests.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |
| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or one that mis-maps the seeded title/tags_json/category values | CARRIED |
| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and does not recreate them (`migrate_videos_schema` drops them on rebuild) | CARRIED |
| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that alters columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |
| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :224 | not storing the code, storing `label` instead of `id`, or storing one value for every video (a-1 `"en"` next to a-2/b-1 NULL) | CARRIED |
| C2b | must_prove | NULL for a null id | :224 (`"a-2": None`) | storing `"null"`, the `"Unknown"` label, or a neighbour's code | CARRIED |
| C2c | must_prove | including in a crawl.db created before the column existed | :256, :260 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |
| D1a | docstring | "every videos table this build touches gains a nullable `language` column" | :116, :224, :260 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :224/:260) | CARRIED |
| D1b | docstring | "...holding the PeerTube language code", which includes the whitelist `videos` table | none | whitelist `language` only ever gets a hand-inserted `'fr'` at :121. Nothing shows a sync carrying a crawl.db code into it | UNCARRIED |
| D2 | docstring | "adds a nullable `language` column" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |
| D3 | docstring | "rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |
| D4 | docstring | "the three `videos_fts_*` triggers still exist" | :119 | triggers lost in a rebuild | CARRIED |
| D5 | docstring | "a title MATCH still finds the preserved row" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |
| D6 | docstring | "and a row inserted afterwards" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |
| D7 | docstring | "a second run leaves `table_info`, the rows and the triggers identical" | :128, :129, :130 | a non-idempotent second run | CARRIED |
| D8a | docstring | "`dist/videos-worker.js`, run under node against local PeerTube stand-ins" | :188, :216, :224 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |
| D8b | docstring | "the committed `dist/videos-worker.js`" | none | the dirty branch at :146-147 accepts an uncommitted dist on mtime alone, so nothing requires the dist to be committed | UNCARRIED |
| D9 | docstring | "`"en"` for a video carrying it" | :224 | storing the label, or nothing | CARRIED |
| D10 | docstring | "NULL for `{"id": null}`" | :224 | storing `"Unknown"` or the string `"null"` | CARRIED |
| D11 | docstring | "NULL for a video with no `language`" | :224 (`"b-1": None`) | a crash or a stale value when the field is absent | CARRIED |
| D12 | docstring | crawl.db seeded from `schema.sql` with the `language` line removed, "so the table really lacks the column" | :232, :246 | a seed that still has the column, which would make C2c vacuous | CARRIED |
| D13 | docstring | "the crawl adds the column" | :256 | no migration of an existing crawl.db | CARRIED |
| D14 | docstring | "keeps the video it did not revisit with `language` NULL" | :260 (`("a-0", "Old one", None)`) | a column add that rebuilds the table and drops rows | CARRIED |
| D15 | docstring | "stores `"de"` on the one it did" | :260 (`("a-1", "A one", "de")`) | an upsert whose `ON CONFLICT` set omits `language` | CARRIED |
| D16 | docstring | "a missing node or git ... fails the test rather than skipping it" | :153, :155 | a `pytest.skip` when a tool is missing | CARRIED |
| D17 | docstring | "a missing or stale dist ... fails the test" | :157, :158 | running a missing or out-of-date build without complaint | CARRIED |
| D18 | docstring | "a nonzero node exit fails the test" | :216, :252 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |
| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |
| N2 | name | `test_crawl_stores_each_videos_language` | :224 | a per-video value that is missing or shared | CARRIED |
| N3 | name | `test_crawl_adds_language_to_existing_db` | :256, :260 | an existing crawl.db that is left without the column | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:1
   D1b is UNCARRIED. The opening sentence says every videos table touched holds "the PeerTube language code". For the whitelist table the only value it ever holds is a hand-written `'fr'` (:121). No assertion shows a code crawled into crawl.db reaching whitelist `videos.language`, which is the job of `rebuild_content_tables` in sync-whitelist.py (listed as EDITED). Either assert that path or narrow the sentence. It is not in `must_prove`, so it does not block.
2. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:4
   D8b is UNCARRIED. The docstring says "the committed `dist/videos-worker.js`", but `_dist_is_stale` (:146-147) falls back to mtime when either file is dirty or uncommitted. An uncommitted dist therefore passes. Either require a committed, clean dist or drop "committed" from the sentence.
3. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:127-130
   Leftover gap in C1d (still CARRIED). After the second run the test checks table_info, five columns of each row, and the trigger names, but not the index. A second run that rebuilds `videos`, recreates the triggers and leaves `videos_fts` empty would pass. Re-running `_matches` after :127 would close this.
4. bounds (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:199
   `language` is tested present-with-id, `{"id": null}` and absent. Malformed shapes are not tested: `language` as a bare string, `language: null`, or a non-string `id`.
5. name-as-sentence (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:99
   `test_migration_adds_language_column` says what happens but not when: on a pre-change whitelist DB, keeping rows and triggers, idempotently. If the test fails on :128-130 (the second run), the runner output still names only "adds language column".

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js, tests/active/test_video_handler.py and tests/active/test_videos_worker.py. I did not read them. The crawl path was judged from engine/crawler/src/db.ts and src/videos-worker.ts, which the test requires the dist to be no older than (:156-158).
2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines everything else itself, so I looked for no conftest.

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - self-check (audit round 2, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase1.py:115, :116, :117, :119, :120, :122, :128, :129, :130, :131. Checked after `migrate_whitelist_schema(conn, "instances")` runs on a pre-change whitelist videos table (the column's absence is confirmed at :109 and the triggers are confirmed at :110). There is exactly one `language` column (:115) and it is nullable (:116). The rows read back as literal seeds with language NULL (:117). The three `videos_fts_*` triggers are present (:119). MATCH still finds v1 (:120), and a row v3 inserted afterwards is also found (:122). A second run leaves table_info (:128), the rows (:129), the triggers (:130) and both MATCH results (:131) unchanged. - expected: `language` table_info notnull 0. Rows [("v1","Alpine walk",'["hike"]',"Travels",None), ("v2","Harbour night",None,None,None)]. Triggers [ad, ai, au]. {"v1"} for "Alpine" and {"v3"} for "Lantern", before and after the second run. Second-run table_info and rows equal the first-run snapshots. - excludes: Today's migration adds nothing, so :115 finds 0 columns. A rebuild through `migrate_videos_schema` drops the triggers, so :119 reads []. A rebuild that never repopulates the index gives :120/:131 an empty set. An unconditional ALTER on the second run raises "duplicate column name: language". A second run that resets rows loses v3's 'fr', which fails :129.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase1.py:225, :257, :261. At :225, the built dist under node crawls two stand-ins and crawl.db holds {a-1: "en", a-2: None, b-1: None}. At :257 and :261, a crawl.db seeded from schema.sql with its language line stripped (absence confirmed at :247) gains the column (:257). The rows then read [("a-0","Old one",None), ("a-1","A one","de")] (:261). - expected: {"a-1": "en", "a-2": None, "b-1": None}. `language` is in the column names. [("a-0","Old one",None), ("a-1","A one","de")]. - excludes: Storing the label gives "English"/"Unknown". Ignoring the field gives all None. A db.ts with no ALTER migration leaves the existing crawl.db without the column, so :257 fails. Adding language to the INSERT but not to `ON CONFLICT DO UPDATE SET` leaves a-1 NULL at :261. A column add that rebuilds the table without copying rows loses a-0.

<exemptions>
none
</exemptions>

<items>
<item id="D1b">
<disposition>justified</disposition>
<what>I narrowed the prose to what the test asserts. Line 1 now reads "The whitelist and crawl.db `videos` tables gain a nullable `language` column, and a crawl fills crawl.db's with the PeerTube language code." Holding the PeerTube code is now claimed only for crawl.db, where :225 and :261 carry it. For the whitelist table the docstring now claims only a nullable column, which :115/:116 carry. The docstring no longer says anything about a sync moving a crawled code into whitelist `videos.language`, and that step is not in this phase's must_prove.</what>
</item>
<item id="D8b">
<disposition>justified</disposition>
<what>I narrowed the prose on line 4. "The committed `dist/videos-worker.js`" is now "The built `dist/videos-worker.js`, no older than its source". That matches what `_require_built_crawler` enforces at :157/:158: the dist must exist and must not predate its source, checked by commit time when both files are clean and committed, and by mtime otherwise. The test no longer claims the dist must be committed.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. I took claim-audit recommendation 3 (the C1d gap: the index is not checked after the second run). New line :131 re-runs `_matches` after the second `migrate_whitelist_schema`, so it now fails on a second run that rebuilds `videos`, recreates the triggers and leaves `videos_fts` empty. I left recommendations 1 and 2 as recommendations, but their UNCARRIED rows D1b and D8b are covered by the prose edits in items. I did not take recommendations 4 (malformed `language` shapes) or 5 (the test name): the first goes beyond this phase's clauses, and renaming would not change what the test gates.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:115, :116, :117, :119, :120, :122, :128, :129, :130, :131. Checked after `migrate_whitelist_schema(conn, "instances")` runs on a pre-change whitelist videos table (the column's absence is confirmed at :109 and the triggers are confirmed at :110). There is exactly one `language` column (:115) and it is nullable (:116). The rows read back as literal seeds with language NULL (:117). The three `videos_fts_*` triggers are present (:119). MATCH still finds v1 (:120), and a row v3 inserted afterwards is also found (:122). A second run leaves table_info (:128), the rows (:129), the triggers (:130) and both MATCH results (:131) unchanged.</assertion>
<expected>`language` table_info notnull 0. Rows [("v1","Alpine walk",'["hike"]',"Travels",None), ("v2","Harbour night",None,None,None)]. Triggers [ad, ai, au]. {"v1"} for "Alpine" and {"v3"} for "Lantern", before and after the second run. Second-run table_info and rows equal the first-run snapshots.</expected>
<wrong_implementation>Today's migration adds nothing, so :115 finds 0 columns. A rebuild through `migrate_videos_schema` drops the triggers, so :119 reads []. A rebuild that never repopulates the index gives :120/:131 an empty set. An unconditional ALTER on the second run raises "duplicate column name: language". A second run that resets rows loses v3's 'fr', which fails :129.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_10_video_metadata_completeness_phase1.py:225, :257, :261. At :225, the built dist under node crawls two stand-ins and crawl.db holds {a-1: "en", a-2: None, b-1: None}. At :257 and :261, a crawl.db seeded from schema.sql with its language line stripped (absence confirmed at :247) gains the column (:257). The rows then read [("a-0","Old one",None), ("a-1","A one","de")] (:261).</assertion>
<expected>{"a-1": "en", "a-2": None, "b-1": None}. `language` is in the column names. [("a-0","Old one",None), ("a-1","A one","de")].</expected>
<wrong_implementation>Storing the label gives "English"/"Unknown". Ignoring the field gives all None. A db.ts with no ALTER migration leaves the existing crawl.db without the column, so :257 fails. Adding language to the INSERT but not to `ON CONFLICT DO UPDATE SET` leaves a-1 NULL at :261. A column add that rebuilds the table without copying rows loses a-0.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every negative assertion (:109 and :247 for the column being absent) is a pre-state control, and a positive assertion after the code under test runs (:115 and :257) depends on it. If the migration or crawler code is deleted, :115, :225 and :257 go red.
2. No. Expected values are literal seeds or literal stand-in payload ids, and the test never computes a language itself. :115 goes red if the ALTER in the whitelist migration is deleted, :225 if the `language?.id` mapping in videos-worker.ts is deleted, and :257 if the ADD COLUMN migration in db.ts is deleted.
3. No. Language is read on three inputs (an id, `{"id": null}` and a missing field), across two instances, in both the insert and the conflict upsert paths.
4. No. The only doubles are the PeerTube HTTP stand-ins, which fake an external service. The project's own migration code, the dist worker and db.js all run for real.
5. Yes, it collects. The only new code is :131, which reuses `_matches`, `conn` and existing names. The file has the same three test functions as before, and the imports are unchanged.
6. Yes. MATCH after a column add, the notnull flag, the trigger names and the crawler's upsert-over-an-existing-row behaviour were all observed in the earlier probes (probe_10_language.py and probe_10_crawl.py). The new :131 expects the same {"v1"}/{"v3"} values those probes saw after the ALTER.
7. Yes, still red for its own reason. Today test 1 fails at :115 (the migration adds no column), and tests 2 and 3 fail at :221 and :257 (no language column in crawl.db). My edits only touched the docstring and added :131 after those failure points, so none of them adds a new way to fail first.
Nothing needed rewriting beyond the two docstring edits and the added :131 assertion.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - red (audit round 2)

`tests/tmp/test_10_video_metadata_completeness_phase1.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase1.py  3 failed                               0.0s
  -------------------------------------------------------
  total                                                    3 failed                               1.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_migration_adds_language_column fails at line 115 on `assert len(language) == 1`,
because migrate_whitelist_schema (whitelist_migrations.py:373-377) only runs the
instances, channels and videos error-column rebuilds, and nothing adds `language`.
test_crawl_stores_each_videos_language fails at line 221 on
`assert "language" in _column_names(conn)`. test_crawl_adds_language_to_existing_db
fails at line 257 on the same column check. Both crawl failures follow from the fact
that no file under engine/ mentions `language` (schema.sql, db.ts, videos-worker.ts
and both dist files included). Either crawl test fails earlier, at line 158 or 159,
if a dist file is missing or older than its source.

NOT ASSESSED
1. `code_under_test` engine/crawler/src/db.ts, src/videos-worker.ts, dist/db.js,
   dist/videos-worker.js and schema.sql were not read in full. The only checks run on
   them were that `crawlVideos` is exported (videos-worker.ts:136, dist/videos-worker.js:15)
   and a grep for `language`, which found no match under engine/.
   tests/active/test_video_handler.py and tests/active/test_videos_worker.py were not
   read. Neither is imported by the audited test.
2. Whether the dist files are currently newer than their sources could not be checked
   without running git. So it is not settled whether the crawl tests go red at line 159
   or at the column checks.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (30 clauses: 7 must_prove, 20 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `migrate_whitelist_schema` adds `videos.language` to a pre-change whitelist DB | :115 | a migration that leaves `videos` without the column (the pre-state is confirmed at :109) | CARRIED |
| C1b | must_prove | keeps every row | :117 | a rebuild that drops rows, or maps the seeded title/tags_json/category values to the wrong columns | CARRIED |
| C1c | must_prove | keeps the three FTS triggers | :119 | a rebuild of `videos` that drops `videos_fts_ai/ad/au` and never recreates them (the pre-state is confirmed at :110) | CARRIED |
| C1d | must_prove | a second run changes nothing | :128, :129, :130 | a second run that changes columns, loses or resets rows (v3's `'fr'` is in the snapshot), or loses the triggers | CARRIED |
| C2a | must_prove | a crawl stores each video's PeerTube language code in crawl.db | :225 | storing no code, storing `label` instead of `id`, or storing one value for every video (a-1 `"en"` sits next to a-2/b-1 NULL) | CARRIED |
| C2b | must_prove | NULL for a null id | :225 (`"a-2": None`) | storing `"null"`, the `"Unknown"` label, or a neighbour's code | CARRIED |
| C2c | must_prove | including in a crawl.db created before the column existed | :257, :261 | a crawler that does not add the column to an existing DB, or whose upsert conflict path leaves `language` unset | CARRIED |
| D1a | docstring | "The whitelist and crawl.db `videos` tables gain a nullable `language` column" | :116, :225, :261 | a NOT NULL column (whitelist at :116; crawl.db holds NULLs at :225/:261) | CARRIED |
| D1b | docstring | withdrawn | n/a | n/a | CARRIED |
| D2 | docstring | "adds a nullable `language` column" (whitelist) | :115, :116 | a missing column, or one declared NOT NULL | CARRIED |
| D3 | docstring | "rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL" | :117 | dropped rows, shifted values, or a non-NULL default | CARRIED |
| D4 | docstring | "the three `videos_fts_*` triggers still exist" | :119 | triggers lost in a rebuild | CARRIED |
| D5 | docstring | "a title MATCH still finds the preserved row" | :120 | `videos_fts` dropped and recreated but never rebuilt from the content table | CARRIED |
| D6 | docstring | "and a row inserted afterwards" | :122 | an insert trigger that exists by name but no longer feeds `videos_fts` | CARRIED |
| D7 | docstring | "a second run leaves `table_info`, the rows and the triggers identical" | :128, :129, :130 | a second run that is not idempotent | CARRIED |
| D8a | docstring | "`dist/videos-worker.js` ... run under node against local PeerTube stand-ins" | :189, :217, :225 | testing the TS source or a mock in place of the dist the crawl actually runs | CARRIED |
| D8b | docstring | withdrawn | n/a | n/a | CARRIED |
| D9 | docstring | "`"en"` for a video carrying it" | :225 | storing the label, or nothing | CARRIED |
| D10 | docstring | "NULL for `{"id": null}`" | :225 | storing `"Unknown"` or the string `"null"` | CARRIED |
| D11 | docstring | "NULL for a video with no `language`" | :225 (`"b-1": None`) | a crash or a stale value when the field is absent | CARRIED |
| D12 | docstring | crawl.db seeded from `schema.sql` with any `language` line removed, "so the table really lacks the column" | :233, :247 | a seed that still has the column, which would make C2c vacuous | CARRIED |
| D13 | docstring | "the crawl adds the column" | :257 | an existing crawl.db that never gets the column | CARRIED |
| D14 | docstring | "keeps the video it did not revisit with `language` NULL" | :261 (`("a-0", "Old one", None)`) | a column add that rebuilds the table and drops rows | CARRIED |
| D15 | docstring | "stores `"de"` on the one it did" | :261 (`("a-1", "A one", "de")`) | an upsert whose `ON CONFLICT` set leaves out `language` | CARRIED |
| D16 | docstring | "A missing node or git ... fails the test rather than skipping it" | :154, :156 | a `pytest.skip` when a tool is missing | CARRIED |
| D17 | docstring | "a missing or stale dist ... fails the test" | :158, :159 | running a missing or out-of-date build without complaint | CARRIED |
| D18 | docstring | "a nonzero node exit fails the test" | :217, :253 | ignoring a crashed crawl and reading whatever is left in the DB | CARRIED |
| N1 | name | `test_migration_adds_language_column` | :115 | a migration that adds nothing | CARRIED |
| N2 | name | `test_crawl_stores_each_videos_language` | :225 | a per-video value that is missing or shared | CARRIED |
| N3 | name | `test_crawl_adds_language_to_existing_db` | :257, :261 | an existing crawl.db left without the column | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:1
   D1b was closed by narrowing the prose, not by adding an assertion. The docstring used to say every `videos` table touched holds the PeerTube language code. It now says only "a crawl fills crawl.db's with the PeerTube language code", which :225 carries. The test still does not show a crawl.db code reaching the whitelist `videos.language`: the only value there is the hand-inserted `'fr'` at :121. `must_prove` C1 does not claim the whitelist column is filled, so no clause is left uncarried.
2. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:4
   D8b was also closed by narrowing the prose. "the committed `dist/videos-worker.js`" is now "The built `dist/videos-worker.js`, no older than its source". Line :159 carries that new clause: `_dist_is_stale` compares commit times for a clean tree and mtimes otherwise (:147-149), so a stale dist fails either way. The check at :157-159 also covers `dist/db.js`, which the docstring does not mention.
3. bounds (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase1.py:200
   The crawl covers three `language` shapes: an id is present, the id is null, and the field is absent. No test covers a malformed one, such as a bare string `"language": "en"`, a non-string id, or `language: null`. So nothing shows the worker stores NULL instead of crashing or writing a non-code value when the payload is malformed. The ledger names no row for this.

NOT ASSESSED
1. `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are listed in `code_under_test`, but this test does not exercise them, so I did not read them.
2. I searched `engine/crawler/src/*.ts`, `engine/crawler/dist/*.js` and `engine/crawler/schema.sql` rather than reading them in full. I checked that `crawlVideos` exists and that the `instances`/`channels` columns the test seeds are defined. I did not check that the `LANGUAGE_LINE` strip at :232 leaves valid SQL, because the column's placement in `schema.sql` could not be seen. If it doesn't, :241 would raise and the test would fail rather than pass vacuously.

## 2026-09-27 - Step 7 - Phase 1 (language column in both producers) - checkpoint outcome (run 1)

`tests/tmp/test_10_video_metadata_completeness_phase1.py` exited 0 after the phase landed.

<changes>
### engine/crawler/schema.sql
- Added `language TEXT,` after `category TEXT,` in `videos`. No index, because the first `db.exec(schemaSql)` runs against old tables.

### engine/crawler/src/db.ts
- New `migrateVideosLanguage(db)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`.
- `applyBaseSchema` calls it after `migrateVideos` and before the second `db.exec(schemaSql)`, so a table the old rebuild just produced also gets the column.
- The `migrateVideos` rebuild carries `language`: new `hasLanguage`/`languageExpr`, `language TEXT` in `videos_new`, and `language` / `${languageExpr}` after `category` in the INSERT and SELECT lists.
- `VideoUpsertRow` has a new field `language: string | null`.
- The upsert has `language` in its INSERT list, 26 `?` before `NULL, NULL, 0`, and `language = excluded.language` in ON CONFLICT. `upsertVideos` passes `row.language` right after `row.category`.
- As the plan says, a re-crawl whose payload has `{id: null}` overwrites crawl.db's `language` with NULL. That matches how `category` is handled.

### engine/crawler/src/videos-worker.ts
- New `PeerTubeLanguage` interface `{ id?: string | null; label?: string }`, and `PeerTubeVideo.language?: PeerTubeLanguage | string`.
- New `extractLanguage`: takes an object's `id` or a plain string, trimmed; a null id, a number, `""` or whitespace gives `null`.
- `toVideoRow` sets `language: extractLanguage(video.language)`.

### engine/crawler/dist/db.js, engine/crawler/dist/videos-worker.js
- Hand-edited to match the source changes above, in tsc's output style: 4-space indent, bodies of one-line `if`s on their own line, JSDoc kept. I couldn't run `npm run build`.
- A throwaway probe (below) ran the edited dist under node against a local PeerTube stand-in. It exited with code 0, and the pre-change crawl.db gained `language` as its last column.
- Rows it produced: `a-0` "Old" not revisited, `language` NULL; `a-1` title updated to "A one" through the conflict path, `language` "de"; `{id: null}` gave NULL; a video with no `language` gave NULL.
- Both dist files were written after their sources, so the checkpoint's mtime staleness check passes while they are uncommitted.
- Recommended before commit, but not needed for the checkpoint: run `cd engine/crawler && npm install && npm run build` and review the dist diff, so the committed dist is real tsc output.

### engine/server/db/jobs/whitelist_migrations.py
- New `migrate_videos_language(conn)`: if `videos` exists and has no `language` column, it runs `ALTER TABLE videos ADD COLUMN language TEXT`. Rows, `videos_fts` and its triggers are untouched, and a second run does nothing.
- `migrate_whitelist_schema` calls it last, after `migrate_videos_schema`.
- The `migrate_videos_schema` rebuild carries `language` conditionally (`has_language`/`language_expr`; column after `category` in `videos_new`, the INSERT list and the SELECT list), so no rebuild can drop it.

### engine/server/db/jobs/sync-whitelist.py
- `ensure_content_schema`'s `CREATE TABLE videos` has a new `language TEXT,` after `category TEXT,`.
- Nothing else changes: `VIDEO_COLUMNS` is parsed from `schema.sql`, so the exact check, the superset check and the copy column list all pick `language` up automatically.

### tests/tmp/probe_10_dist_language.py
- The throwaway probe described above. I have no delete tool, so I overwrote it with an empty file; it collects no tests. Please delete it.

### Not touched
- `tests/active/test_video_handler.py` and `tests/active/test_videos_worker.py` are in the phase's files list, but they are test files that the checkpoint promotion carries. This step is production code only, so I left them alone.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_10_dist_language.py - a throwaway probe used to watch the hand-edited dist run under node. Emptied, because I have no tool that deletes files; the operator should remove it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_10_video_metadata_completeness_phase1.py  3 passed                               0.0s
  -------------------------------------------------------
  total                                                    3 passed                               1.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (default display labels in /api/video) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The `/api/video` response built by `handle_video_request` carries `category` and `language` as PeerTube default display labels from the new `engine/server/data/peertube_labels.py`, while the stored values stay ids and codes.

- C1 - A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored.
- C2 - A stored language code is answered with its PeerTube default label, and an unknown code is answered raw.

must_prove:
- C1 - A stored digit-only category id is answered with its PeerTube default label, and an unknown id or a text category is answered as stored.
- C2 - A stored language code is answered with its PeerTube default label, and an unknown code is answered raw.

## 2026-09-27 - Step 7 - Phase 2 (default display labels in /api/video) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase2.py:82 — `body.get("category", "MISSING") == expected_category` over five DB-only cases (fetch stubbed to None): "15"→"Science & Technology", "18"→"Food", "99"→"99", "19"→"19", "Music"→"Music"; backed on a success refresh by :104 (`category == "Science & Technology"` for a stored "15") and :103 (stored category is still "15") - expected: "Science & Technology", "Food", "99", "19", "Music" for the five cases, and "Science & Technology" at :104. The current code sends no `category` key at all; the run showed 'MISSING' at :82 in all five cases and at :104. - excludes: No mapping, just adding `"category": category` to the response: "15" and "18" answer raw "15"/"18", red. A map missing an entry or shifted by one (e.g. only ids 1–17): "18" answers "18" instead of "Food", red. A lookup that returns "" or None for an unknown id, or one that tries int() on any value: "99", "19" or "Music" answers ""/None or raises, red. A handler that turns the stored value into the label before the UPDATE and writes it back: :103 reads "Science & Technology" instead of "15", red.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase2.py:83 — `body.get("language", "MISSING") == expected_language` over "en"→"English", "zh-Hans"→"Simplified Chinese", "xx"→"xx"; backed by :105 (`language == "English"` on a success refresh with stored "en") and :103 (stored language is still "en") - expected: "English", "Simplified Chinese", "xx", and "English" at :105. The current code sends no `language` key: the probe's captured body had no `language` at all, so today :83 and :105 read 'MISSING'. The run never reached them because the category check fails first. - excludes: Sending the raw code (`"language": row["language"]`): "en" answers "en", red. A lookup that lowercases or strips the region part: "zh-Hans" becomes "zh-hans" or "zh" and answers raw or "Chinese" instead of "Simplified Chinese", red. An unknown code mapped to "" or "Unknown": "xx" answers that, red. Not selecting `v.language` in `fetch_video_row`: every case answers ""/MISSING, red. Writing the label back into the row: :103 reads "English", red.

<assertions>
tests/tmp/test_10_video_metadata_completeness_phase2.py:79 - `handle_video_request` sends exactly one response. This guards the capture the other assertions read. (setup, all clauses)
tests/tmp/test_10_video_metadata_completeness_phase2.py:81 - that response has status 200, so the row was found and the answer came from the DB path. (setup, all clauses)
tests/tmp/test_10_video_metadata_completeness_phase2.py:82 - the response `category` is the PeerTube default label for a stored digit-only id: "15" → "Science & Technology", and "18" → "Food" (the last default id). An unknown id is answered as stored: "99", and "19" (one past the default range). A text category is answered as stored: "Music". A missing key reads "MISSING", so an unchanged handler fails here instead of raising KeyError. A hard-coded label fails because the five cases disagree, and so does an off-by-one range or a map applied to text. # C1
tests/tmp/test_10_video_metadata_completeness_phase2.py:83 - the response `language` is the PeerTube default label for a stored code: "en" → "English", "zh-Hans" → "Simplified Chinese" (a case-sensitive code). An unknown code "xx" is answered raw as "xx". A `fetch_video_row` that never selects `v.language` gives "" or "MISSING" and fails. # C2
tests/tmp/test_10_video_metadata_completeness_phase2.py:86 - after the request the stored `(category, language)` still equals the raw id and code the test wrote. This catches an implementation that relabels before the handler's existing UPDATE and so writes labels back into the row. # C1 C2
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_10_phase2_labels.py", "-s"]. The probe used the checkpoint's harness: tmp_path DB from sync-whitelist.py `ensure_whitelist_schema` + `ensure_content_schema`, one instance, one channel and one video seeded, the row UPDATEd to ("15", "en"), `respond_json` captured, and `fetch_instance_json` stubbed to None. It printed:
- videos columns include `language` (phase 1 is in place), and instances has `last_error`, `last_error_at` and `last_error_source`.
- `handle_video_request` returned True and called `fetch_instance_json` once, with ('peer.example', '/api/v1/videos/v1').
- It sent one response: 200 with the 18 existing keys and no `category` or `language` key.
- Stored (category, language) after the request was ('15', 'en'). `last_checked_at` was bumped, which is the phase-3 defect and not asserted here.
Command: ValidateTests ["tests/tmp/test_10_video_metadata_completeness_phase2.py"] against the current tree. All 5 cases fail at line 82 with `assert 'MISSING' == <expected>`, which is the intended red: setup and the 200 status pass. The probe file could not be deleted with the tools I have, so I emptied it. It collects no tests; please remove tests/tmp/probe_10_phase2_labels.py.
Not observed: the language labels "English" and "Simplified Chinese" were not checked against a running PeerTube instance, because there is no network. They come from the Step 6 checkpoint and the plan's R4 draft, which match PeerTube's `buildLanguages()` (`languages['zh-Hans'] = 'Simplified Chinese'`) as I recall it. A `GET /api/v1/videos/languages` on a stock instance would confirm them. The same call is the step the plan already needs for replacing `LANGUAGE_LABELS`. "Science & Technology", "Food" and the 1–18 range come straight from R4's list.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_video_metadata_completeness_phase2.py` - 4118 characters, inlined in full

```
"""`/api/video` answers the stored category and language as PeerTube default display labels, and leaves the stored id and code as they were.

- With the instance fetch failing, so the answer comes from the DB: a stored "15" answers "Science & Technology", "18" answers "Food", and an unknown id ("99", "19") or a text category ("Music") answers as stored.
- A stored "en" answers "English", "zh-Hans" answers "Simplified Chinese", and an unknown code ("xx") answers "xx".
- After the request the row still holds the raw category and language it was given.

The DB is built by `sync-whitelist.py`'s own schema helpers; `respond_json` and `fetch_instance_json` are replaced on `handlers.video`, and the instance is never contacted.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from handlers import video  # noqa: E402

HOST = "peer.example"
PARAMS = {"id": ["v1"], "host": [HOST]}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path):
    sync_job = _load_job("sync_whitelist_video_labels", "sync-whitelist.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 5, 'video')", (HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count) VALUES ('7', ?, 'oldslug', 'Old Chan', 3)", (HOST,))
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, title, category, language, published_at, last_checked_at) VALUES ('v1', 'uuid-1', ?, '7', 'Old Chan', 'Old title', 'Music', 'fr', 1600000000000, 1000)", (HOST,))
    conn.commit()
    try:
        yield SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("category", "language", "expected_category", "expected_language"),
    [
        ("15", "en", "Science & Technology", "English"),
        ("99", "zh-Hans", "99", "Simplified Chinese"),
        ("Music", "xx", "Music", "xx"),
        # The ends of PeerTube's 1-18 default range: the last id resolves, the next one is unknown.
        ("18", "en", "Food", "English"),
        ("19", "xx", "19", "xx"),
    ],
    ids=["id-and-code", "unknown-id", "text-and-unknown-code", "last-id", "past-last-id"],
)
def test_response_labels(server, monkeypatch, category, language, expected_category, expected_language):
    server.db.execute("UPDATE videos SET category = ?, language = ? WHERE video_id = 'v1'", (category, language))
    server.db.commit()
    responses = []
    monkeypatch.setattr(video, "respond_json", lambda handler, status, body: responses.append((status, body)))
    monkeypatch.setattr(video, "fetch_instance_json", lambda host, path: None)

    video.handle_video_request(None, server, PARAMS)

    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    assert body.get("category", "MISSING") == expected_category  # C1
    assert body.get("language", "MISSING") == expected_language  # C2
    # Labels are a display concern only: the row keeps what the crawler wrote, which FTS and embeddings read.
    stored = tuple(server.db.execute("SELECT category, language FROM videos WHERE video_id = 'v1'").fetchone())
    assert stored == (category, language)  # C1 C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (default display labels in /api/video) - red (audit round 1)

`tests/tmp/test_10_video_metadata_completeness_phase2.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase2.py  6 failed                               0.0s
  -------------------------------------------------------
  total                                                    6 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (default display labels in /api/video) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Every case of test_response_labels fails at line 82 because `body.get("category", "MISSING")`
returns "MISSING": the `response` dict built in handle_video_request (video.py:271-290) has no
"category" key yet. test_refresh_stores_raw_codes gets past lines 102-103 (title updated,
row keeps "15"/"en") and fails at line 104 for the same reason: `body.get("category", "MISSING")`
gives "MISSING", not "Science & Technology".

NOT ASSESSED
1. `code_under_test` listed engine/server/data/peertube_labels.py (NEW), which is not there yet,
   so I could not read it. The test does not import it and reaches it only through
   handlers.video. I answered the stub question from the assertion form and the handler.
2. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which is not there
   either, so I could not read it. It is not the test under audit, and I made no finding from it.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 5 must_prove, 12 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a stored digit-only category id is answered with its PeerTube default label | :82 (`15`, `18` rows) | returning the stored id unchanged, and a label table that stops short of the top of the 1-18 range | CARRIED |
| C1b | must_prove | an unknown id is answered as stored | :82 (`99`, `19` rows) | mapping an unknown id to empty, None or a placeholder, and an off-by-one table that resolves 19 | CARRIED |
| C1c | must_prove | a text category is answered as stored | :82 (`Music` row) | nulling or relabelling a category that is not digits | CARRIED |
| C2a | must_prove | a stored language code is answered with its PeerTube default label | :83 (`en`, `zh-Hans` rows) | returning the raw code, and a lookup on the primary subtag only that answers `zh-Hans` as plain "Chinese" | CARRIED |
| C2b | must_prove | an unknown code is answered raw | :83 (`xx` rows) | mapping an unknown code to empty, None or a placeholder | CARRIED |
| D1 | docstring | "answers the stored category ... as PeerTube default display labels" | :82 | a response with no category field (the `"MISSING"` default fails) or the raw id | CARRIED |
| D2 | docstring | "answers the stored ... language as PeerTube default display labels" | :83 | a response with no language field, or the raw code | CARRIED |
| D3 | docstring | "leaves the stored id and code as they were" | :103 | writing the label into `videos.category` / `videos.language` | CARRIED |
| D4 | docstring | fetch failing: "15" answers "Science & Technology", "18" answers "Food" | :82 | raw passthrough, and a truncated table | CARRIED |
| D5 | docstring | unknown id ("99", "19") or text category ("Music") answers as stored | :82 | replacing unmapped values | CARRIED |
| D6 | docstring | "en" answers "English", "zh-Hans" answers "Simplified Chinese" | :83 | raw passthrough, and subtag-truncated lookup | CARRIED |
| D7 | docstring | unknown code ("xx") answers "xx" | :83 | replacing an unmapped code | CARRIED |
| D8 | docstring | a successful refresh with an id-only category and a code-only language "writes the row" | :102 | a refresh path that skips the UPDATE (title stays "Old title", last_checked_at stays 1000) | CARRIED |
| D9 | docstring | refresh "keeps '15' and 'en' stored" | :103 | persisting the label, or nulling the id when the source has no label | CARRIED |
| D10 | docstring | refresh "answers 'Science & Technology' and 'English'" | :104, :105 | a refresh path whose response bypasses the label mapping | CARRIED |
| D11 | docstring | "DB is built by `sync-whitelist.py`'s own schema helpers" | :46-47 (by construction) | a hand-written schema that drifts from production | CARRIED |
| D12 | docstring | "the instance is never contacted" | :75, :93 (by construction) | a real fetch: `fetch_instance_json` is replaced outright, and video.py has no other `urlopen` path | CARRIED |
| N1 | name | `test_response_labels`: the response carries labels | :82, :83 | a response without labels | CARRIED |
| N2 | name | `test_refresh_stores_raw_codes`: the refresh stores raw codes | :103 | a refresh that stores labels | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase2.py:58-68
   The top of the 1-18 category range is tested (`18` resolves, `19` does not), but the bottom is not: `1` and `0` never run. The shapes that still count as "digit-only" are also untested: `"015"`, `""`, and a NULL `category` or `language` column. C1's claim is about digit-only ids, so these are the edges that decide what counts as an id.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase2.py:70
   No case stores a NULL category or language, so nothing shows how a missing stored value is answered. The fixture row at :50 always holds values, and every parametrised row overwrites both with non-empty strings.
3. name-as-sentence (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase2.py:70, :86
   `test_response_labels` and `test_refresh_stores_raw_codes` are noun phrases, not sentences saying what should happen and when. An example would be "answers stored category id and language code as default labels when the instance fetch fails". The parametrise ids at :68 carry some of the "when", but the names do not.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` listed engine/server/data/peertube_labels.py, which does not resolve (no match anywhere in the tree). I could not check the label table the test's expected values are meant to match, such as `18` → "Food" or `zh-Hans` → "Simplified Chinese". Bounds were judged from the test's own comment that the range is 1-18 (:64).
2. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve. I could not assess what was edited there.
3. engine/server/api/handlers/video.py was read as it currently stands. It has no label mapping and puts no `language` field in the response. Accepted inputs and failure behaviour were judged from that version, not the edited one.

## 2026-09-27 - Step 7 - Phase 2 (default display labels in /api/video) - checkpoint outcome (run 1)

`tests/tmp/test_10_video_metadata_completeness_phase2.py` exited 0 after the phase landed.

<changes>
### engine/server/data/peertube_labels.py (NEW)
- A stdlib-only module that follows the `data/*.py` style: a module docstring, `from __future__ import annotations`, and a docstring on each function. It does no work at import beyond the literals.
- `CATEGORY_LABELS` maps `"1"`–`"18"` to exactly the labels listed in R4. A `rat-tail:` comment names the ceiling (stock PeerTube lists only; plugin-added or renamed entries show raw) and the upgrade path (cache each instance's `/api/v1/videos/categories` and `/api/v1/videos/languages`).
- `LANGUAGE_LABELS` is the stock instance's `GET /api/v1/videos/languages` body that the operator pasted during this step, copied verbatim onto one line. This is the Step 6 manual replacement, and the plan's from-memory draft was never committed. The live list differs from the draft in places: `es` is "Spanish (Spain)", `pt` is "Portuguese (Brazilian)", `km` is "Khmer", and it adds `es-419`, `ca-valencia`, `zxx`, `gcf`, `gcr`, `rcf`, `gsw`, `sh` and `fse`. `en` → "English" and `zh-Hans` → "Simplified Chinese" are both there.
- `category_label(value)`: returns `""` when the value is empty or not a string. A string that is all ASCII digits (`isascii()` plus `isdigit()`) goes through the map, and an unknown id comes back unchanged. Any other value is returned as it is.
- `language_label(value)`: returns `""` when the value is empty or not a string. Otherwise it does a case-sensitive lookup, and an unknown code comes back raw.

### engine/server/api/handlers/video.py (EDITED)
- Imports `category_label` and `language_label` from `data.peertube_labels`.
- `fetch_video_row` now also selects `v.language`.
- The response dict gains two keys, and all existing keys are unchanged:
  - `"category"`: `category_label(category)`. `category` is the existing merged value (source first, then the DB).
  - `"language"`: `language_label(row.get("language"))`.
- Labels are applied only when building the response. The UPDATE still writes the raw merged `category`, and `language` is not written at all yet, so the stored id and code stay as they were. That is what `test_refresh_stores_raw_codes` checks.
- Not in this phase: language merging from the source, the success-only write guard and the other R5 keys. They belong to Phase 3.

### tests/active/test_video_handler.py
- Not touched. It is on the phase's files list, but it holds the checkpoint that checkpoint promotion carries. This step is production code only.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_10_video_metadata_completeness_phase2.py  6 passed                               0.0s
  -------------------------------------------------------
  total                                                    6 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`handle_video_request` in `engine/server/api/handlers/video.py` writes to the DB only when the video detail fetch returns a JSON object, and on success it stores and answers one merged source-over-DB value set, including tags, category, language, nsfw, duration and thumbnail.

- C1 - A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values.
- C2 - A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values.

must_prove:
- C1 - A caught network error or a malformed detail body leaves every videos, channels and instances.last_error* value unchanged, and the response answers the DB values.
- C2 - A successful detail fetch writes the source value for each field present and the DB value for each field absent, and the response answers the same merged values.

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase3.py:149 — for all five failures (urlopen raising URLError, a 404 status whose body is `{}`, `<html>`, `\xff\xfe`, `[1, 2]`, each served by a fake `urlopen` so the real `fetch_instance_json` runs), the `SELECT *` videos row, every `SELECT *` channels row and `instances.last_error*` equal the snapshot taken before the request - expected: The snapshot is unchanged: popularity stays 0.0, last_checked_at stays 1000, and the instance error stays ('boom', 5, 'video'). - excludes: Today's code turns the failed fetch into `{}` and still writes. The run showed urlopen-urlerror and status-404 red here, with popularity 0.0→0.0402…, last_checked_at 1000→1790556048333 and the instance error cleared to (None, None, None). A parse guard that catches only JSONDecodeError still raises on bad UTF-8, and one that lets a list through raises AttributeError. In the run, not-json, bad-utf8 and json-list all raised out of `handle_video_request` (JSONDecodeError at video.py:86, UnicodeDecodeError at :85, AttributeError at :167).
- C1 - tests/tmp/test_10_video_metadata_completeness_phase3.py:150 — the failure response answers the stored values: title, description, views, tags, category, language label, duration, thumbnailUrl and channelName - expected: {"title": "Old title", "description": "Old desc", "views": 1, "tags": ["old"], "category": "Music", "language": "French", "duration": 10, "thumbnailUrl": "https://peer.example/old.jpg", "channelName": "Old Chan"} - excludes: A handler that never adds the new keys reads "MISSING" for tags, duration and thumbnailUrl; today's response has no such keys. A failure path that answers nulls or blanks instead of the DB row reads None or "" for those fields.
- C1 - tests/tmp/test_10_video_metadata_completeness_phase3.py:151 — the failure response `nsfw` is exactly False - expected: False (the seeded 0, converted to a bool) - excludes: With no nsfw key the check reads "MISSING". If the raw DB integer passes through it reads 0, and the `is` check rejects that.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:167 — after a full SOURCE payload, served as JSON through the real `fetch_instance_json`, the whole videos row equals the seed with only the source fields replaced; popularity and last_checked_at are left free - expected: title "New title", description "New desc", channel_name "New Chan", views 50, likes 5, dislikes 1, category "Science & Technology", language "en", nsfw 1, duration 321, thumbnail_url "https://peer.example/static/thumbnails/new.jpg"; every other column is as seeded - excludes: An UPDATE that does not extend its SET list leaves the new columns alone. The run showed today's code keeping language 'fr', duration 10 and thumbnail_url 'https://peer.example/old.jpg'. Storing the label instead of the code would give language "English". Leaving `thumbnailPath` relative would store "/static/thumbnails/new.jpg".
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:172 — the success response answers the same merged values - expected: title "New title", description "New desc", views 50, likes 5, dislikes 1, tags ["alpha", "beta"], category "Science & Technology", language "English", duration 321, thumbnailUrl "https://peer.example/static/thumbnails/new.jpg", channelName "New Chan", subscribersCount 9 - excludes: A response built from the pre-write DB row, or one without the new keys, gives stale values or "MISSING" for tags, duration and thumbnailUrl. A response that echoes the stored language code gives "en" instead of "English".
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:194 — for a partial payload in two forms, `{"views": 77}` and one with a blank name and description, null tags, category, nsfw, duration and thumbnailPath, and `language {"id": null}`, the row equals the seed with only views 77 changed; the control at :193 first proves the write ran - expected: Only views changes, to 77. tags_json stays '["old"]', category 'Music', language 'fr', nsfw 0, duration 10 and thumbnail_url the old URL; popularity and last_checked_at are left free. - excludes: If the merge writes `resolve_asset_url`'s "" for a missing thumbnail, thumbnail_url reads "". If null tags are turned into "[]", tags_json reads "[]". A null language id stored as-is gives language NULL, and writing a blank title or description gives "  " or "". Today's code passes this line only because it never writes those columns; its red comes at :196.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:196 — the partial-payload response answers the kept DB values, with views 77 - expected: {"title": "Old title", "description": "Old desc", "views": 77, "tags": ["old"], "category": "Music", "language": "French", "duration": 10, "thumbnailUrl": "https://peer.example/old.jpg", "channelName": "Old Chan"} - excludes: A response that uses the source value whenever the key is present answers None or "" for the absent fields. Today's code answers "MISSING" for tags, duration and thumbnailUrl, and the run showed exactly those three keys differing.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:206 and :207 — `tags: []` stores exactly "[]" and answers [] - expected: tags_json == "[]" and response tags == [] - excludes: The current `to_tags_json` turns an empty list into None, so the stored value is kept. The run showed '["old"]' at :206. A response parser that falls back to the DB when the list is empty would answer ["old"].
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:219 and :221 — the raw bodies `{"name": "Fresh title", "duration": 42}` and `{}`, read through the real `fetch_instance_json`, both count as a success. The stored (title, duration, last_checked_at moved) and the answered (title, duration) follow the merge: source values where present, DB values where absent - expected: object: ("Fresh title", 42, True) stored and ("Fresh title", 42) answered; empty-object: ("Old title", 10, True) stored and ("Old title", 10) answered - excludes: A success guard written as `if not detail` treats `{}` as a failure and writes nothing, so last_checked_at stays 1000 and :219 reads ("Old title", 10, False). Today's code never writes duration: the run showed ('Fresh title', 10, True) at :219 for the object case, and ('Old title', 'MISSING') at :221 for the empty object.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:233 and :235 — two requests are made, and the source renames the video and changes its tags in between. Both responses and the final row carry the source values of their own request - expected: responses [("New title", ["alpha", "beta"]), ("Renamed", ["gamma"])]; stored ("Renamed", ["gamma"]) - excludes: A handler that answers from the row it read before writing gives the first request's values on the second response. Today's code has no tags key, and the run showed ('New title', 'MISSING') at index 0 on :233.

<assertions>
tests/tmp/test_10_video_metadata_completeness_phase3.py:150 - control: the seeded `instances.last_error*` is ("boom", 5, "video") before the request, so the equality at :160 cannot pass on two NULL snapshots. (setup, C1)
tests/tmp/test_10_video_metadata_completeness_phase3.py:156/:158 - control: the detail fetch really ran. For stub-none the stub was asked for `/api/v1/videos/v1`. For the urlopen cases the fake was called with `https://peer.example/api/v1/videos/v1` and timeout 8, which is the kept fetch contract. A handler that never fetches cannot pass the untouched-DB check this way. (setup, C1)
tests/tmp/test_10_video_metadata_completeness_phase3.py:160 - for all five failures (stub-none, urlopen-urlerror, not-json, bad-utf8, json-list) the `SELECT *` videos row, every `SELECT *` channels row and `instances.last_error*` equal the snapshot taken before. Today's code fails this: stub-none and URLError move `last_checked_at` and `popularity` and clear the instance error, and the three bodies raise. # C1
tests/tmp/test_10_video_metadata_completeness_phase3.py:161 - the failure response carries the DB values: title "Old title", description "Old desc", views 1, tags ["old"], category "Music", language "French", duration 10, thumbnailUrl "https://peer.example/old.jpg", channelName "Old Chan". A missing key reads "MISSING". # C1
tests/tmp/test_10_video_metadata_completeness_phase3.py:162 - the failure response `nsfw` is the bool False (identity check, so a raw 0 fails). # C1
tests/tmp/test_10_video_metadata_completeness_phase3.py:174 - on a full SOURCE payload the stored tags_json parses to ["alpha", "beta"]. It is compared parsed so that JSON spacing and ensure_ascii are not asserted. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:176 - `last_checked_at` moved past the seeded 1000. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:178 - the whole videos row equals the seed with exactly these overrides: title, description, channel_name "New Chan", views 50, likes 5, dislikes 1, category "Science & Technology", language "en" (the code, not the label), nsfw 1, duration 321, thumbnail_url "https://peer.example/static/thumbnails/new.jpg" (thumbnailPath made absolute). Only popularity and last_checked_at are free. Today's code fails here: language stays "fr", duration stays 10 and the thumbnail stays old. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:179 - the channels row is refreshed to ("newslug", "New Chan", 9). # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:180 - `instances.last_error*` are all NULL after a success. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:181 - all 18 original response keys are still present. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:183 - the response answers the same merged values: title, description, views, likes, dislikes, tags ["alpha", "beta"], category "Science & Technology", language "English", duration 321, thumbnailUrl equal to the stored absolute URL, channelName "New Chan", subscribersCount 9. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:184 - the success response `nsfw` is True. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:205 - for a partial payload, in two forms: `absent` ({"views": 77}) and `null-or-blank` (name "  ", description "", and null tags, category, nsfw, duration and thumbnailPath, plus language {"id": null}). The whole row equals the seed with only views 77 changed, and last_checked_at and popularity left free. This catches blank thumbnail "" overwrites, tags None turned into "[]", a null language id stored as anything, and a blank title or description written. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:207 - the partial-payload response answers the stored values with views 77: tags ["old"], category "Music", language "French", duration 10, the old thumbnail, "Old title", "Old desc". # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:208 - the partial-payload response `nsfw` is False. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:217 - `tags: []` stores exactly "[]", the literal R2 form. Today's code keeps '["old"]'. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:218 - `tags: []` answers `[]`. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:228 - control: the fake urlopen was reached at the video URL with timeout 8. (setup, C2)
tests/tmp/test_10_video_metadata_completeness_phase3.py:230 - a JSON object body read through the real `fetch_instance_json` is a success: `{"name": "Fresh title"}` stores "Fresh title", and `{}` keeps "Old title". Both move last_checked_at. This is the success side of the json-list case, so a guard that also rejects an empty object fails here. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:231 - in the same test, `instances.last_error*` are cleared. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:232 - in the same test, the response title equals the stored title. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:245 - control: the first of two requests answered "New title" with tags ["alpha", "beta"]. (setup, C2)
tests/tmp/test_10_video_metadata_completeness_phase3.py:246 - the second request, after the source renamed the video and changed its tags, answers "Renamed" with ["gamma"]. # C2
tests/tmp/test_10_video_metadata_completeness_phase3.py:248 - after the second request the row holds title "Renamed" and tags that parse to ["gamma"]. # C2
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_10_phase3_refresh.py", "-s"], output read from tests/last_test_output.txt. The probe used the same harness as the checkpoint: a DB from sync-whitelist.py `ensure_whitelist_schema` + `ensure_content_schema`, the instance seeded with last_error 'boom'/5/'video', channel '7' 'oldslug'/'Old Chan'/3, and video v1 with every refreshed column seeded.
- Labels: `language_label("fr")` = 'French', `language_label("en")` = 'English', `category_label("Science & Technology")` = 'Science & Technology', `category_label("Music")` = 'Music'.
- Seeded row via `SELECT *`: popularity 0.0, last_checked_at 1000, nsfw 0, duration 10, thumbnail_url 'https://peer.example/old.jpg', tags_json '["old"]', language 'fr'.
- stub-none today: the row's popularity went 0.0 → 0.0402…, last_checked_at 1000 → 1790555758382, and instances.last_error* went to (None, None, None). The channels row was unchanged. Response keys, exactly 20: videoUuid, title, description, channelName, channelUrl, channelAvatarUrl, subscribersCount, instanceName, instanceUrl, accountName, accountUrl, accountAvatarUrl, embedUrl, originalUrl, views, likes, dislikes, publishedAt, category ('Music'), language ('French'). There was no tags, nsfw, duration or thumbnailUrl key.
- The fake urlopen (a `_FakeResponse` with status 200, `__enter__`/`__exit__` and `read()`) was called with ('https://peer.example/api/v1/videos/v1', 8, {'Accept': 'application/json'}). Today `<html>` raises JSONDecodeError, `\xff\xfe` raises UnicodeDecodeError, and `[1, 2]` raises AttributeError ('list' object has no attribute 'get').
- urlopen raising URLError("down") today: one call (url, 8). The DB was written just as in stub-none: last_checked_at bumped, popularity changed, instance error cleared.
- The SOURCE payload today, via a path-keyed stub: the paths asked for were ['/api/v1/videos/v1', '/api/v1/video-channels/newslug']. The row got title/description/views/likes/dislikes, tags_json '["alpha", "beta"]', category 'Science & Technology', nsfw 1 and channel_name 'New Chan'. language stayed 'fr', duration stayed 10 and thumbnail_url stayed old. Channels became ('newslug', 'New Chan', 9). The response had channelName 'New Chan', subscribersCount 9 and channelUrl 'https://peer.example/video-channels/newslug'.
The probe file tests/tmp/probe_10_phase3_refresh.py is now empty, because I have no tool that deletes files. The operator should remove it.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_video_metadata_completeness_phase3.py` - 12340 characters, inlined in full

```
"""`/api/video` writes the stored video only when the detail fetch returns a JSON object, and on success stores and answers one source-over-DB value set.

- A failed detail fetch (the fetch returning None, `urlopen` raising `URLError`, a body that is not JSON, a body that is not UTF-8, a JSON list) leaves the whole videos row, every channels row and `instances.last_error*` as they were, and answers 200 with the stored title, description, views, tags, category, language, nsfw, duration, thumbnail and channel name.
- A full source payload writes title, description, stats, tags, category, language code, nsfw, duration, absolute thumbnail URL and the channel, moves `last_checked_at` forward, clears `instances.last_error*`, leaves every other column as seeded, keeps the 18 original response keys and answers the same values (category and language as labels, tags as a list, nsfw as a bool).
- A payload that omits a field, or sends it null, blank or with a null language id, keeps the stored value in the row and in the response; `tags: []` stores "[]" and answers `[]`.
- A JSON object body read through the real `fetch_instance_json`, `{}` included, counts as a success.
- A source change between two requests is in the second response and in the row.

The DB is built by `sync-whitelist.py`'s own schema helpers; `respond_json` and either `fetch_instance_json` or `urlopen` are replaced on `handlers.video`, and the instance is never contacted.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from handlers import video  # noqa: E402

HOST = "peer.example"
PARAMS = {"id": ["v1"], "host": [HOST]}
OLD_CHECKED_AT = 1000
VIDEO_PATH = "/api/v1/videos/v1"
VIDEO_URL = f"https://{HOST}{VIDEO_PATH}"
CHANNEL_PATH = "/api/v1/video-channels/newslug"
OLD_THUMBNAIL = "https://peer.example/old.jpg"
NEW_THUMBNAIL = "https://peer.example/static/thumbnails/new.jpg"
SOURCE = {"name": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": {"id": 15, "label": "Science & Technology"}, "language": {"id": "en", "label": "English"}, "nsfw": True, "duration": 321, "thumbnailPath": "/static/thumbnails/new.jpg", "channel": {"name": "newslug", "displayName": "New Chan"}}
# The keys /api/video answered before this build; the probe printed exactly these 18.
ORIGINAL_KEYS = {"videoUuid", "title", "description", "channelName", "channelUrl", "channelAvatarUrl", "subscribersCount", "instanceName", "instanceUrl", "accountName", "accountUrl", "accountAvatarUrl", "embedUrl", "originalUrl", "views", "likes", "dislikes", "publishedAt"}
STORED_ANSWER = {"title": "Old title", "description": "Old desc", "views": 1, "tags": ["old"], "category": "Music", "language": "French", "duration": 10, "thumbnailUrl": OLD_THUMBNAIL, "channelName": "Old Chan"}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path):
    sync_job = _load_job("sync_whitelist_video_refresh", "sync-whitelist.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 5, 'video')", (HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count) VALUES ('7', ?, 'oldslug', 'Old Chan', 3)", (HOST,))
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, title, description, tags_json, category, language, nsfw, duration, thumbnail_url, views, likes, dislikes, published_at, last_checked_at) VALUES ('v1', 'uuid-1', ?, '7', 'Old Chan', 'Old title', 'Old desc', '[\"old\"]', 'Music', 'fr', 0, 10, ?, 1, 1, 0, 1600000000000, ?)", (HOST, OLD_THUMBNAIL, OLD_CHECKED_AT))
    conn.commit()
    try:
        yield SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)
    finally:
        conn.close()


@pytest.fixture
def responses(monkeypatch):
    captured = []
    monkeypatch.setattr(video, "respond_json", lambda handler, status, body: captured.append((status, body)))
    return captured


class _FakeResponse:
    def __init__(self, body: bytes):
        self.status = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _serve(monkeypatch, payloads: dict) -> list[str]:
    """Replace the instance fetch with a path-keyed fake and return the paths it was asked for."""
    paths = []

    def fetch(host, path):
        paths.append(path)
        return payloads.get(path)

    monkeypatch.setattr(video, "fetch_instance_json", fetch)
    return paths


def _serve_body(monkeypatch, outcome) -> list[tuple[str, object]]:
    """Replace `urlopen` one level below `fetch_instance_json`, so its real parse guard runs; returns (url, timeout) per call."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append((req.full_url, timeout))
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(video, "urlopen", fake_urlopen)
    return calls


def _video(conn) -> dict:
    return dict(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone())


def _instance_errors(conn) -> tuple:
    return tuple(conn.execute("SELECT last_error, last_error_at, last_error_source FROM instances WHERE host = ?", (HOST,)).fetchone())


def _snapshot(conn) -> tuple:
    return (tuple(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone()), tuple(tuple(row) for row in conn.execute("SELECT * FROM channels ORDER BY channel_id")), _instance_errors(conn))


def _only_body(responses) -> dict:
    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    return body


def _answered(body: dict, expected: dict) -> dict:
    return {key: body.get(key, "MISSING") for key in expected}


@pytest.mark.parametrize("outcome", [None, URLError("down"), b"<html>", b"\xff\xfe", b"[1, 2]"], ids=["stub-none", "urlopen-urlerror", "not-json", "bad-utf8", "json-list"])
def test_fetch_failure_leaves_db_untouched(server, monkeypatch, responses, outcome):
    if outcome is None:
        paths = _serve(monkeypatch, {})
    else:
        calls = _serve_body(monkeypatch, outcome)
    before = _snapshot(server.db)
    assert before[2] == ("boom", 5, "video"), "the seeded instance error is what the comparison must preserve"

    video.handle_video_request(None, server, PARAMS)

    # The detail fetch was really attempted, so an untouched DB is not just a handler that never fetched.
    if outcome is None:
        assert paths[:1] == [VIDEO_PATH]
    else:
        assert calls[:1] == [(VIDEO_URL, 8)]
    body = _only_body(responses)
    assert _snapshot(server.db) == before  # C1
    assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1
    assert body.get("nsfw", "MISSING") is False  # C1


def test_success_refreshes_row_and_response(server, monkeypatch, responses):
    before = _video(server.db)
    _serve(monkeypatch, {VIDEO_PATH: SOURCE, CHANNEL_PATH: {"followersCount": 9}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    after = _video(server.db)
    # tags_json is compared parsed: the JSON spacing and escaping are not part of the contract.
    assert json.loads(after.pop("tags_json")) == ["alpha", "beta"]  # C2
    before.pop("tags_json")
    assert after["last_checked_at"] > OLD_CHECKED_AT  # C2
    # popularity and last_checked_at are derived at write time; every other column is either a source value or the untouched seed.
    assert after == {**before, "title": "New title", "description": "New desc", "channel_name": "New Chan", "views": 50, "likes": 5, "dislikes": 1, "category": "Science & Technology", "language": "en", "nsfw": 1, "duration": 321, "thumbnail_url": NEW_THUMBNAIL, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}  # C2
    assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 9)  # C2
    assert _instance_errors(server.db) == (None, None, None)  # C2
    assert ORIGINAL_KEYS <= body.keys()  # C2
    expected = {"title": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": "Science & Technology", "language": "English", "duration": 321, "thumbnailUrl": NEW_THUMBNAIL, "channelName": "New Chan", "subscribersCount": 9}
    assert _answered(body, expected) == expected  # C2
    assert body.get("nsfw", "MISSING") is True  # C2


@pytest.mark.parametrize(
    "payload",
    [
        {"views": 77},
        # Null, blank and a null language id are all "absent" under the mapping rules, not values to store.
        {"views": 77, "name": "  ", "description": "", "tags": None, "category": None, "language": {"id": None, "label": "Unknown"}, "nsfw": None, "duration": None, "thumbnailPath": None},
    ],
    ids=["absent", "null-or-blank"],
)
def test_partial_payload_keeps_tags_and_category(server, monkeypatch, responses, payload):
    before = _video(server.db)
    _serve(monkeypatch, {VIDEO_PATH: payload})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    after = _video(server.db)
    assert after["last_checked_at"] > OLD_CHECKED_AT, "the refresh did not write the row"
    assert after == {**before, "views": 77, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}  # C2
    expected = {**STORED_ANSWER, "views": 77}
    assert _answered(body, expected) == expected  # C2
    assert body.get("nsfw", "MISSING") is False  # C2


def test_empty_tag_list_propagates(server, monkeypatch, responses):
    _serve(monkeypatch, {VIDEO_PATH: {"tags": []}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    assert _video(server.db)["tags_json"] == "[]"  # C2
    assert body.get("tags", "MISSING") == []  # C2


@pytest.mark.parametrize(("body", "title"), [(b'{"name": "Fresh title"}', "Fresh title"), (b"{}", "Old title")], ids=["object", "empty-object"])
def test_object_body_counts_as_success(server, monkeypatch, responses, body, title):
    calls = _serve_body(monkeypatch, body)

    video.handle_video_request(None, server, PARAMS)

    reply = _only_body(responses)
    assert calls[:1] == [(VIDEO_URL, 8)]
    stored = _video(server.db)
    assert (stored["title"], stored["last_checked_at"] > OLD_CHECKED_AT) == (title, True)  # C2
    assert _instance_errors(server.db) == (None, None, None)  # C2
    assert reply.get("title") == title  # C2


def test_second_request_reflects_source_change(server, monkeypatch, responses):
    payloads = {VIDEO_PATH: SOURCE, CHANNEL_PATH: {"followersCount": 9}}
    _serve(monkeypatch, payloads)

    video.handle_video_request(None, server, PARAMS)
    payloads[VIDEO_PATH] = {**SOURCE, "name": "Renamed", "tags": ["gamma"]}
    video.handle_video_request(None, server, PARAMS)

    assert [status for status, _ in responses] == [200, 200]
    first, second = (body for _, body in responses)
    assert (first.get("title"), first.get("tags", "MISSING")) == ("New title", ["alpha", "beta"])
    assert (second.get("title"), second.get("tags", "MISSING")) == ("Renamed", ["gamma"])  # C2
    stored = _video(server.db)
    assert (stored["title"], json.loads(stored["tags_json"])) == ("Renamed", ["gamma"])  # C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - red (audit round 1)

`tests/tmp/test_10_video_metadata_completeness_phase3.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase3.py  12 failed                              0.0s
  -------------------------------------------------------
  total                                                    12 failed                              0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 4 UNCARRIED clause(s) - C1d, C2d, C2g, D13b; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_fetch_failure_leaves_db_untouched[urlopen-urlerror] and [status-404] should fail at line 149
(`assert _snapshot(server.db) == before`). The row is written even when the fetch fails:
fetch_instance_video_dynamic returns a non-empty dict of Nones, so `if dynamic` holds, which moves
`last_checked_at` and sets `instances.last_error*` to NULL. The [not-json], [bad-utf8] and [json-list]
cases should error at line 144, because JSONDecodeError, UnicodeDecodeError and
AttributeError (`list.get`) escape `handle_video_request`. test_success_refreshes_row_and_response
should fail at line 167 on the row dict: `language` stays "fr" instead of "en", `duration` stays 10
instead of 321, and `thumbnail_url` keeps OLD_THUMBNAIL. The UPDATE never writes those columns.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_video_handler.py, which does not resolve in this
   worktree, so it was not read.
2. `fixtures_path` was not supplied. The test defines its own `server` and `responses` fixtures and
   otherwise uses only pytest built-ins (tmp_path, monkeypatch). The only conftest found,
   tests/active/conftest.py, does not cover tests/tmp, so it was not read.
```

Basis for PASS (shape.md, read over tests/tmp/test_10_video_metadata_completeness_phase3.py):

- **Anti-patterns pass:**
  - No `.md` file is read and no substring assertions are made, so doc-lint-grep, section-scoped-substring-grep and whole-file-source-name-grep do not apply.
  - hardcoded-spec-mirror: `ORIGINAL_KEYS` (line 44) is checked with a subset test against the handler's output (line 170), not against a code constant.
  - tautological-assertion: every expected value is a literal or the independent seed (`before`). `popularity` and `last_checked_at` are left out of the comparison, not computed the way the code computes them, and `last_checked_at` gets its own `>` check (line 165).
  - absence-only-assertion: the "unchanged" check in C1 (line 149) is paired with positive checks in the same test. Line 147 checks the fetch was attempted, and lines 150–151 check the stored values in the response.
  - echoed-literal: `handle_video_request` runs between every input and every assertion.
  - single-value-pin: seeded values and source values differ on every asserted field (title, description, views, category, language fr/en, nsfw 0/1, duration 10/321/42, thumbnail, channel name, followers 3/9). The partial, empty-object and second-request tests show the output following the input across several inputs.
- **Ladder pass:** Rung 1. The handler is called directly, with assertions on its captured response and on the database changes it makes. There is no CLI or subprocess boundary, so no higher rung applies. The test is not at a lower rung, so the downshift rule does not apply.
- **Stub question:** The test would fail against a stub. The previous behaviour left as it was fails both C1 and C2 as predicted above. A hard-coded response fails too, because expected titles, views and tags differ across the parametrized cases and across the two requests (lines 229–235). The `urlopen` mock sits below the real `fetch_instance_json`, so the real parsing runs. It does not let a stub pass.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (34 clauses: 11 must_prove, 17 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a caught network error ... leaves every videos, channels and instances.last_error* value unchanged" | :149 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :147 shows the fetch was attempted | CARRIED |
| C1b | must_prove | "a malformed detail body" leaves the same values unchanged | :149 (404, not-json, bad-utf8, json-list params :138) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |
| C1c | must_prove | "the response answers the DB values": the metadata fields | :150, :151 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |
| C1d | must_prove | "the response answers the DB values": likes, dislikes, subscribersCount (seeded 1, 0, 3) | none | nothing. `STORED_ANSWER` (:45) leaves out all three, so a failure path that answers any value for them passes | UNCARRIED |
| C2a | must_prove | "writes the source value for each field present": the videos row | :163, :165, :167 | any source field dropped, left at the seed or mis-mapped. Every column is compared against `{**before, ...}` | CARRIED |
| C2b | must_prove | "writes the source value for each field present": the channels row | :168 | slug, display name or followers not written from the source | CARRIED |
| C2c | must_prove | "the DB value for each field absent": the videos row | :194 (absent and null-or-blank params) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |
| C2d | must_prove | "the DB value for each field absent": the channels row | none | nothing. No success-path test with an absent channel, or a failed channel-detail fetch, reads back the channels row | UNCARRIED |
| C2e | must_prove | "the response answers the same merged values": present fields | :170, :172, :173 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |
| C2f | must_prove | response answers the merged values: absent metadata fields | :196, :197 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |
| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | none | nothing. `expected = {**STORED_ANSWER, "views": 77}` (:195) leaves them out, so the row (:194) and the response can disagree | UNCARRIED |
| D1 | docstring | "writes the stored video only when the detail fetch returns a JSON object" | :149, :219 | writing on a non-object body, or not writing on an object body | CARRIED |
| D2 | docstring | "on success stores and answers one source-over-DB value set" | :167, :172 | the row and the response diverging on present fields | CARRIED |
| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :138 params, :149 | any listed kind treated as success | CARRIED |
| D4 | docstring | "leaves the whole videos row, every channels row and instances.last_error* as they were" | :149 | a partial write on failure | CARRIED |
| D5 | docstring | "answers 200 with the stored title, description, views, tags, category, language, nsfw, duration, thumbnail and channel name" | :129, :150, :151 | a non-200 reply, or any named field not the stored value | CARRIED |
| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :163, :167, :168 | any named field not written, or a relative thumbnail stored | CARRIED |
| D7 | docstring | "moves last_checked_at forward" | :165 | `last_checked_at` left unchanged | CARRIED |
| D8 | docstring | "clears instances.last_error*" | :169 | the seeded error left in place | CARRIED |
| D9 | docstring | "leaves every other column as seeded" | :167 | a write to a column outside the mapping | CARRIED |
| D10 | docstring | "keeps the 18 original response keys" | :170 | an original key dropped | CARRIED |
| D11 | docstring | "answers the same values (category and language as labels, tags as a list, nsfw as a bool)" | :172, :173 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |
| D12 | docstring | omitted, null, blank or null-language-id field "keeps the stored value in the row" | :194 | overwriting with NULL or blank | CARRIED |
| D13a | docstring | "... and in the response": the fields named in STORED_ANSWER | :196, :197 | the response answering blanks for those fields | CARRIED |
| D13b | docstring | "... and in the response": omitted likes and dislikes | none | nothing, same gap as C2g | UNCARRIED |
| D14 | docstring | "`tags: []` stores "[]" and answers `[]`" | :206, :207 | an empty list treated as absent (old tags kept) | CARRIED |
| D15 | docstring | "A JSON object body, `{}` included, counts as a success" | :219, :220, :221 | `{}` treated as failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |
| D16 | docstring | "A source change between two requests is in the second response and in the row" | :233, :235 | a cached or first-write-only value | CARRIED |
| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :60-61, :75, :110 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:103) | CARRIED |
| N1 | name | "fetch failure leaves db untouched" | :149 | a write on failure | CARRIED |
| N2 | name | "success refreshes row and response" | :167, :172 | a stale row or response after success | CARRIED |
| N3 | name | "partial payload keeps tags and category" | :194 | tags_json or category overwritten (both inside `before`) | CARRIED |
| N4 | name | "empty tag list propagates" | :206, :207 | `[]` ignored | CARRIED |
| N5 | name | "object body counts as success" | :219 | `{}` or an object body not written | CARRIED |
| N6 | name | "second request reflects source change" | :233, :235 | the first fetch's values persisting | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:150
   `assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1`
   C1 says the failure response "answers the DB values". `STORED_ANSWER` (:45) leaves out `likes`, `dislikes` and `subscribersCount`, though the seed stores 1, 0 and 3 and the success test does assert them (:171). Nothing checks these three on the failure path, so an implementation that answers a default or `None` for them after a failed fetch passes. This is C1d.
2. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:194
   `assert after == {**before, "views": 77, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}  # C2`
   C2 says a successful fetch writes "the DB value for each field absent". This only checks the videos row. No success-path test reads back the channels row when the channel fields are absent: the partial and object payloads carry no `channel`, and no test fails the `/api/v1/video-channels/...` fetch while the detail fetch succeeds. An implementation that writes NULL slug, display name or followers into `channels` in that case passes. This is C2d.
3. whole-claim (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:195
   `expected = {**STORED_ANSWER, "views": 77}`
   C2 says the response "answers the same merged values". On the absent-field path the response assertion leaves out `likes`, `dislikes` and `subscribersCount`, while :194 pins `likes` and `dislikes` in the row. A response that disagrees with the row it just wrote passes. This is C2g, and it also covers D13b.

RECOMMENDATIONS
1. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:42
   No payload sends a present falsy value, such as `views: 0`, `likes: 0`, `nsfw: False` over a stored 1, or `duration: 0`. A merge written as `source or db` treats these as absent and passes every test here, so C2a's "each field present" is untested at zero.
2. bounds (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:138
   The malformed-body cases do not include an empty body `b""`, a JSON `null`, or a JSON scalar (`b"3"`, `b'"x"'`). The caught-error cases cover `URLError` only. `TimeoutError`, which the fetch path catches alongside it, is not exercised.
3. name-as-sentence (rules/testing.md): tests/tmp/test_10_video_metadata_completeness_phase3.py:185
   `test_partial_payload_keeps_tags_and_category` asserts that every column is kept (:194), and the response too. When description or duration regresses, the runner output names tags and category, so it does not tell the reader what broke.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_handler.py, which does not exist at this path. Nothing in it was read.
2. `fixtures_path` was not supplied. The test defines its own fixtures (:55, :72), and the only conftest found (tests/active/conftest.py) does not cover tests/tmp/. No outside fixture was needed.

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - self-check (audit round 2, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase3.py:150 — the full videos row, every channels row and instances.last_error* all equal the pre-request snapshot, for URLError, 404, not-json, bad-utf8 and json-list. :151 — the response answers STORED_ANSWER: title, description, views 1, likes 1, dislikes 0, tags ["old"], category "Music", language "French", duration 10, the old thumbnail, channelName "Old Chan", subscribersCount 3. :152 — nsfw is False. - expected: Snapshot unchanged, including ("boom", 5, "video"). The response carries the seeded DB values, and nsfw is the bool False. - excludes: Today's code writes on URLError and 404: last_checked_at goes 1000 → now, popularity moves, and the instance error is cleared. The three bad bodies raise. A failure path that answers None or a default for likes, dislikes or subscribersCount, or leaves out tags, duration or thumbnailUrl ("MISSING"), fails :151.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase3.py:164/:166/:168/:169/:170/:171/:173/:174 — full SOURCE: row, channels, cleared error, original keys and merged response. :196/:197/:199/:200 — absent and null-or-blank payloads: the row keeps the seed except views 77, channels rows are unchanged, and the response is STORED_ANSWER with views 77 (likes 1, dislikes 0, subscribersCount 3 included) and nsfw False. :211/:212 — failed channel-detail fetch: channels ("newslug", "New Chan", 3), and the response channelName "New Chan" with subscribersCount 3. :221/:222 — tags [] stores "[]" and answers []. :234–:236 — an object body, {} included, is a success. :248/:250 — the second request reflects the source change. - expected: Source values where present, DB values where absent, in the videos row, the channels row and the response alike. - excludes: Today's code leaves language "fr", duration 10 and the old thumbnail in the row after a full payload (fails :168). It answers no tags, duration or thumbnailUrl (fails :199 as "MISSING", observed). A merge that writes NULL followers after a failed channel fetch fails :211. One that nulls the channel slug or display name on an absent channel fails :197. A response that disagrees with the row on likes, dislikes or subscribersCount fails :199.

<exemptions>
none
</exemptions>

<items>
<item id="C1d">
<disposition>fixed</disposition>
<what>`STORED_ANSWER` (:46) now includes `"likes": 1, "dislikes": 0, "subscribersCount": 3`, which are the seeded videos.likes, videos.dislikes and channels.followers_count. So :151 (`_answered(body, STORED_ANSWER) == STORED_ANSWER`) now checks all three on every failure kind. This rules out a failure path that answers None, 0 or a default for them. The failure-bullet docstring now names likes, dislikes and subscriber count.</what>
</item>
<item id="C2d">
<disposition>fixed</disposition>
<what>There are two new assertions. (a) :197 in `test_partial_payload_keeps_tags_and_category`: `_snapshot(server.db)[1] == channels_before`. Every `SELECT *` channels row must match the pre-request snapshot on a success where the payload has no channel. This rules out NULL slug, display name or followers being written into `channels`. (b) The new `test_failed_channel_fetch_keeps_stored_followers`: the detail fetch returns SOURCE, and the `/api/v1/video-channels/newslug` fetch raises `URLError`, which :210 confirms was attempted. :211 asserts the channels row is ("newslug", "New Chan", 3). Slug and display name are present, so they are written. Followers are absent, so the stored 3 stays. This rules out NULL or 0 followers after a failed channel-detail fetch. Both expected values were observed in a probe run. The docstring now states both behaviours.</what>
</item>
<item id="C2g">
<disposition>fixed</disposition>
<what>`expected = {**STORED_ANSWER, "views": 77}` (:198) now includes likes 1, dislikes 0 and subscribersCount 3 through the widened `STORED_ANSWER`. So :199 requires the absent-field response to match the row pinned at :196 and the channels row pinned at :197. :212 also asserts that `subscribersCount` is 3 after a failed channel fetch.</what>
</item>
<item id="D13b">
<disposition>fixed</disposition>
<what>This is the same change as C2g. :199 now checks that omitted likes and dislikes answer the stored 1 and 0, and subscribersCount the stored 3. The docstring's partial bullet also now says the channels row is left as it was.</what>
</item>
</items>

<findings_addressed>
claim CRITICAL 1 (C1d, :150): I added likes 1, dislikes 0 and subscribersCount 3 to `STORED_ANSWER`, so the failure-response assertion (now :151) checks them on all five failure kinds.
claim CRITICAL 2 (C2d, :194): I added :197, which checks that the channels rows are unchanged on an absent-channel success. I also added `test_failed_channel_fetch_keeps_stored_followers` (:203–:212), which checks the channels row ("newslug", "New Chan", 3) and subscribersCount 3 when the channel-detail fetch fails.
claim CRITICAL 3 (C2g/D13b, :195): the widened `STORED_ANSWER` puts likes, dislikes and subscribersCount into `expected` at :198, so the response at :199 has to match the row at :196.
shape audit: no CRITICAL. The new assertions compare against seeded literals and probe-observed values, not a copy of the production mapping. Recommendations 1–3 were not taken, to keep this round inside the ledger.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:150 — the full videos row, every channels row and instances.last_error* all equal the pre-request snapshot, for URLError, 404, not-json, bad-utf8 and json-list. :151 — the response answers STORED_ANSWER: title, description, views 1, likes 1, dislikes 0, tags ["old"], category "Music", language "French", duration 10, the old thumbnail, channelName "Old Chan", subscribersCount 3. :152 — nsfw is False.</assertion>
<expected>Snapshot unchanged, including ("boom", 5, "video"). The response carries the seeded DB values, and nsfw is the bool False.</expected>
<wrong_implementation>Today's code writes on URLError and 404: last_checked_at goes 1000 → now, popularity moves, and the instance error is cleared. The three bad bodies raise. A failure path that answers None or a default for likes, dislikes or subscribersCount, or leaves out tags, duration or thumbnailUrl ("MISSING"), fails :151.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_10_video_metadata_completeness_phase3.py:164/:166/:168/:169/:170/:171/:173/:174 — full SOURCE: row, channels, cleared error, original keys and merged response. :196/:197/:199/:200 — absent and null-or-blank payloads: the row keeps the seed except views 77, channels rows are unchanged, and the response is STORED_ANSWER with views 77 (likes 1, dislikes 0, subscribersCount 3 included) and nsfw False. :211/:212 — failed channel-detail fetch: channels ("newslug", "New Chan", 3), and the response channelName "New Chan" with subscribersCount 3. :221/:222 — tags [] stores "[]" and answers []. :234–:236 — an object body, {} included, is a success. :248/:250 — the second request reflects the source change.</assertion>
<expected>Source values where present, DB values where absent, in the videos row, the channels row and the response alike.</expected>
<wrong_implementation>Today's code leaves language "fr", duration 10 and the old thumbnail in the row after a full payload (fails :168). It answers no tags, duration or thumbnailUrl (fails :199 as "MISSING", observed). A merge that writes NULL followers after a failed channel fetch fails :211. One that nulls the channel slug or display name on an absent channel fails :197. A response that disagrees with the row on likes, dislikes or subscribersCount fails :199.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every unchanged-state check has a positive control: :148 shows the fetch was attempted, :195 shows the row was written, and :210 shows the channel fetch was attempted and failed.
2. No. Expected values are seeded literals or probe-observed source values. Deleting the `row.get("channel_followers_count")` fallback in `handle_video_request` turns :211/:212 red, and the same goes for the row/likes fallbacks at :199.
3. No. subscribersCount is read at 3 (stored, on failure, partial and failed-channel runs) and 9 (source). Likes/dislikes are read at 1/0 (stored) and 5/1 (source).
4. No. Only `respond_json` and `urlopen` are replaced. Both are severed I/O layers, and the project's `fetch_instance_json` runs for real.
5. Yes, it collects. I imported the module's tests into a probe and ran it: 8 cases collected, with no import or name errors.
6. Yes. Likes 1, dislikes 0 and subscribersCount 3 on failure and partial paths, the call list [video, channel], and channels ("newslug", "New Chan", 3) after a failed channel fetch were all observed in a probe run (tests/tmp/probe_10_phase3_channels.py) before I wrote them down. The probe file is now empty, since I have no delete tool, so the operator should remove it along with tests/tmp/probe_10_phase3_refresh.py.
7. Yes, it is still red for the phase. The probe run of the edited test showed the failure cases red at :150 (the DB was written) or raising in the fetch (JSONDecodeError, UnicodeDecodeError, AttributeError), and the partial cases red at :199 on missing tags, duration and thumbnailUrl. The new `test_failed_channel_fetch_keeps_stored_followers` passes against today's code. It guards behaviour that already exists and that the phase must keep, and it is not a gap the phase fills.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - red (audit round 2)

`tests/tmp/test_10_video_metadata_completeness_phase3.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase3.py  12 failed, 1 passed                    0.0s
  -------------------------------------------------------
  total                                                    12 failed, 1 passed                    0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No shape.md entry covers this: stub question, previous behaviour. Location: tests/tmp/test_10_video_metadata_completeness_phase3.py:211-212
   `assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 3)  # C2`
   `test_failed_channel_fetch_keeps_stored_followers` passes against video.py as it stands. The current handler already falls back to `row["channel_followers_count"]` when the channel-detail fetch fails. That fallback is correct for this case. A wrong implementation that wrote `None` or dropped the fallback would still fail here, so this is not a stub-pass. But this test will not be red in the observed run, and it does not gate the phase's change.

PREDICTED FAILURE
Against the code as it stands:
- test_fetch_failure_leaves_db_untouched:
  - [urlerror] and [status-404] fail at line 150 (`_snapshot(server.db) == before`). `dynamic` is a non-empty dict, so the handler writes anyway: it advances `last_checked_at` and `popularity` and sets `instances.last_error*` to NULL.
  - [not-json], [bad-utf8] and [json-list] error at line 145. `fetch_instance_json` does not catch `JSONDecodeError` or `UnicodeDecodeError`, and a JSON list raises `AttributeError` on `detail.get`.
- test_success_refreshes_row_and_response fails at line 168. The row keeps `language='fr'`, `duration=10` and the old `thumbnail_url`.
- Both test_partial_payload_keeps_tags_and_category cases fail at line 199. The response has no `duration` or `thumbnailUrl` key, so each reads as "MISSING".
- test_empty_tag_list_propagates fails at line 221. `to_tags_json([])` returns None, so `tags_json` stays `'["old"]'`.
- test_object_body_counts_as_success:
  - [object] fails at line 234 because `duration` stays 10.
  - [empty-object] fails at line 236 because `duration` is "MISSING" in the reply.
- test_second_request_reflects_source_change fails at line 248 because `tags` is "MISSING" in both responses.
- test_failed_channel_fetch_keeps_stored_followers passes (see Recommendation 1).

NOT ASSESSED
1. `code_under_test` listed tests/active/test_video_handler.py (EDITED), which does not resolve (FileNotFoundError). Its edits were not read.
2. `fixtures_path` was not supplied. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/. Every fixture the test uses (`server`, `responses`) is defined in the test file itself, so nothing was left unresolved.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (37 clauses: 11 must_prove, 20 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a caught network error ... leaves every videos, channels and instances.last_error* value unchanged" | :150 | a write on the `URLError` path. The whole videos row, all channels rows and the seeded `('boom', 5, 'video')` are compared, and :148 shows the fetch was attempted | CARRIED |
| C1b | must_prove | "a malformed detail body" leaves the same values unchanged | :150 (404, not-json, bad-utf8, json-list params :139) | a non-200, non-JSON, non-UTF-8 or list body being treated as success and written | CARRIED |
| C1c | must_prove | "the response answers the DB values": the metadata fields | :151, :152 | the response answering blanks or defaults for title, description, views, tags, category, language, nsfw, duration, thumbnailUrl or channelName on failure | CARRIED |
| C1d | must_prove | "the response answers the DB values": likes, dislikes, subscribersCount (seeded 1, 0, 3) | :151 | `STORED_ANSWER` (:46) now holds `"likes": 1, "dislikes": 0, ... "subscribersCount": 3`, so the test fails if the failure path answers any other value for these three | CARRIED |
| C2a | must_prove | "writes the source value for each field present": the videos row | :164, :166, :168 | any source field dropped, left at the seed or mapped to the wrong column. Every column is compared against `{**before, ...}` | CARRIED |
| C2b | must_prove | "writes the source value for each field present": the channels row | :169 | slug, display name or followers not written from the source | CARRIED |
| C2c | must_prove | "the DB value for each field absent": the videos row | :196 (absent and null-or-blank params :180-182) | NULL or blank written over a stored value for an omitted, null or blank field | CARRIED |
| C2d | must_prove | "the DB value for each field absent": the channels row | :197, :211 | an absent `channel` rewriting the channels row (:197), or a failed channel-detail fetch writing NULL over the stored follower count of 3 (:211) | CARRIED |
| C2e | must_prove | "the response answers the same merged values": present fields | :171, :173, :174 | the response answering DB values, raw codes instead of labels, or a non-bool nsfw after a full source fetch | CARRIED |
| C2f | must_prove | response answers the merged values: absent metadata fields | :199, :200 | the response answering blanks for absent title, description, tags, category, language, duration, thumbnail, channelName or nsfw | CARRIED |
| C2g | must_prove | response answers the merged values: absent likes, dislikes, subscribersCount | :199 | `expected = {**STORED_ANSWER, "views": 77}` (:198) now includes 1, 0 and 3, so the test fails if the response disagrees with the row (:196) on these fields | CARRIED |
| D1 | docstring | "writes the stored video only when the detail fetch returns a JSON object" | :150, :234 | writing on a non-object body, or not writing on an object body | CARRIED |
| D2 | docstring | "on success stores and answers one source-over-DB value set" | :168, :173 | the row and the response disagreeing on present fields | CARRIED |
| D3 | docstring | failure kinds: URLError, non-200, not JSON, not UTF-8, JSON list | :139 params, :150 | any listed kind treated as success | CARRIED |
| D4 | docstring | "leaves the whole videos row, every channels row and instances.last_error* as they were" | :150 | a partial write on failure | CARRIED |
| D5 | docstring | "answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count" | :130, :151, :152 | a non-200 reply, or any named field answered with something other than the stored value | CARRIED |
| D6 | docstring | full payload writes title ... absolute thumbnail URL and the channel | :164, :168, :169 | any named field not written, or a relative thumbnail stored | CARRIED |
| D7 | docstring | "moves last_checked_at forward" | :166 | `last_checked_at` left unchanged | CARRIED |
| D8 | docstring | "clears instances.last_error*" | :170 | the seeded error left in place | CARRIED |
| D9 | docstring | "leaves every other column as seeded" | :168 | a write to a column outside the mapping | CARRIED |
| D10 | docstring | "keeps the 18 original response keys" | :171 | an original key dropped | CARRIED |
| D11 | docstring | "answers the same values (category and language as labels, tags as a list, nsfw as a bool)" | :173, :174 | raw codes, a JSON string for tags, or 1/0 for nsfw | CARRIED |
| D12 | docstring | omitted, null, blank or null-language-id field "keeps the stored value in the row" | :196 | overwriting with NULL or blank | CARRIED |
| D13a | docstring | "... and in the response": the fields named in STORED_ANSWER | :199, :200 | the response answering blanks for those fields | CARRIED |
| D13b | docstring | "... and in the response": omitted likes and dislikes | :199 | the response answering anything other than the stored 1 and 0. Both are now in `STORED_ANSWER` | CARRIED |
| D14 | docstring | "`tags: []` stores "[]" and answers `[]`" | :221, :222 | an empty list treated as absent, so the old tags are kept | CARRIED |
| D15 | docstring | "A JSON object body, `{}` included, counts as a success" | :234, :235, :236 | `{}` treated as a failure: no `last_checked_at` bump, and the error is not cleared | CARRIED |
| D16 | docstring | "A source change between two requests is in the second response and in the row" | :248, :250 | a cached value, or one written only on the first fetch | CARRIED |
| D17 | docstring | real schema helpers; `respond_json`/`urlopen` replaced; the real `fetch_instance_json` parses every body; the instance is never contacted | :61-62, :76, :111 (setup, not assertions) | a real network call. Unlisted paths raise `URLError` (:104) | CARRIED |
| N1 | name | "fetch failure leaves db untouched" | :150 | a write on failure | CARRIED |
| N2 | name | "success refreshes row and response" | :168, :173 | a stale row or response after success | CARRIED |
| N3 | name | "partial payload keeps tags and category" | :196 | tags_json or category overwritten (both are inside `before`) | CARRIED |
| N4 | name | "empty tag list propagates" | :221, :222 | `[]` ignored | CARRIED |
| N5 | name | "object body counts as success" | :234 | `{}` or another object body not written | CARRIED |
| N6 | name | "second request reflects source change" | :248, :250 | the first fetch's values persisting | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase3.py:6, :212
   New docstring sentence, not in the ledger: "A failed channel-detail fetch writes the source channel slug and display name and keeps the stored follower count, in the channels row and in the response."
   - The row half is carried at :211.
   - In the response, :212 asserts `channelName` and `subscribersCount` only. The slug reaches the response only through `channelUrl`, and nothing asserts `channelUrl`.
   - So the test still passes if the response builds `channelUrl` from the stored `oldslug` instead of the source `newslug`. The "slug ... in the response" part of this sentence is uncarried.
   - The same gap is in the full-payload test. :173 does not assert `channelUrl` either, even though the channel slug is a present field under C2e.
   - To fix this, assert `channelUrl` or narrow the sentence.
2. Clauses added since the ledger that are carried, for the record:
   - Docstring :5, "and leaves the channels row as it was", is carried at :197.
   - The new test name `test_failed_channel_fetch_keeps_stored_followers` is carried at :211 and :212.
   - D5's sentence was widened to add likes, dislikes and subscriber count, not narrowed. It is carried at :151.
3. The round-one UNCARRIED rows C1d, C2d, C2g and D13b were fixed by new assertions, not by narrowing the prose:
   - `STORED_ANSWER` was extended (:46).
   - A channels-row check was added at :197.
   - A new failed-channel-fetch test was added (:203-212).

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_handler.py, which doesn't exist; a Glob for `**/test_video_handler*.py` found nothing. It was not read.
2. `fixtures_path` was not supplied. Every fixture the test uses (`server`, `responses`) is defined in the test file, apart from pytest's own `tmp_path` and `monkeypatch`, so no conftest was needed. The schema helpers `ensure_whitelist_schema` and `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py were not read.

## 2026-09-27 - Step 7 - Phase 3 (refresh only on success, one merge) - checkpoint outcome (run 1)

`tests/tmp/test_10_video_metadata_completeness_phase3.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/handlers/video.py`
- **`fetch_video_row`** now also selects `v.duration` and `v.thumbnail_url`, so a failed fetch can still answer them from the DB. `v.language` was already selected in phase 2.
- **`fetch_instance_json`** returns a `dict` or `None`. It still calls `urlopen(req, timeout=8)`, still catches `HTTPError`/`URLError`/`TimeoutError`, and a non-200 status still returns `None`. Two more cases return `None` and log at info:
  - a `ValueError` (this covers both `UnicodeDecodeError` and `JSONDecodeError`);
  - a parsed body that is not a `dict`.
  The `# pragma: no cover` on the except line is gone.
- **New helpers:**
  - `pick_present(value, fallback)`: returns the source value unless it is None, otherwise the DB value.
  - `id_text`: turns an int (never a bool) or a non-empty trimmed string into text.
  - `tags_from_json`: parses the stored `tags_json` into its string tags. Null, empty, invalid or non-list values give `[]`.
  - `extract_language`: returns an object's `id`, or a plain non-empty string, through `pick_text`. A null id gives `None`.
- **Changed helpers:**
  - `to_tags_json` returns `"[]"` for an empty list, and `None` only when the value is not a list. It writes raw UTF-8 (`ensure_ascii=False`) to match the crawler, as the settled draft decided.
  - `extract_category` falls back to the id as text when there is no label. Plain values go through `id_text`, so `""` or whitespace keeps the DB value.
- **`fetch_instance_video_dynamic`** returns `None` exactly when the detail fetch gives no dict. This is the single success signal. `account` and `channel` are guarded with `isinstance(dict)`. The function now also returns:
  - `language`, from `extract_language`;
  - `duration`, from `pick_number`;
  - `thumbnail_url`, from `resolve_asset_url(thumbnailUrl or thumbnailPath)`, with `""` mapped to `None` so a missing thumbnail never blanks the stored one.
  The channel-detail fallback is unchanged, so if that second fetch fails, the stored follower count is kept.
- **`handle_video_request`**
  - If there is no host, or the fetch fails, `dynamic` is `None` and `source = {}`.
  - One merged value set (source value where present, else the DB value) now covers title, description, stats, channel, tags_json, category, language, nsfw, duration and thumbnail_url. The same set feeds the response and the UPDATE.
  - The response keeps all 18 original keys. `accountAvatarUrl` now reads from `source`. Four keys are added: `tags` (a list), `nsfw` (a bool or null), `duration` and `thumbnailUrl`. `language` now labels the merged code rather than the DB row's code.
  - The write guard is now `dynamic is not None`, which checks identity rather than truthiness. On failure no `videos`, `channels` or `instances` statement runs. A `{}` body still counts as a success.
  - The `videos` UPDATE also sets `language`, `duration` and `thumbnail_url`. The `channels` UPDATE, the `instances.last_error*` reset, the transaction and the `OperationalError` catch are unchanged.

### `tests/active/test_video_handler.py`
Not touched. The phase lists it as EDITED, but it does not exist in this worktree. This phase's checkpoint lives in `tests/tmp/test_10_video_metadata_completeness_phase3.py`, and I did not edit that file either. Presumably it is moved into `tests/active` at harvest.

Not run: I did not execute the checkpoint myself. I checked it by reading each test's cases against the code. The phase 2 checkpoint (`test_refresh_stores_raw_codes`, where an id-only category is now stored as `"15"` rather than keeping the DB value) should also stay green under the new rules, but that too is from reading, not from a run.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_10_video_metadata_completeness_phase3.py  13 passed                              0.0s
  -------------------------------------------------------
  total                                                    13 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (taxonomy block on the video page) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The video page (`video-page.html`, `pages/video-page/index.ts`, `video.css`) has a `video-taxonomy` block that shows the category, language and tags from `/api/video` as text only.

- C1 - For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag.
- C2 - For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads "No tags".

must_prove:
- C1 - For an `/api/video` body with a category, a language and tags, the block shows the category value, the language value and one text chip per tag.
- C2 - For an `/api/video` body with an empty category, language and tag list, the category and language items are hidden and the tag list reads "No tags".

## 2026-09-27 - Step 7 - Phase 4 (taxonomy block on the video page) - self-check (audit round 1, send-back 0)

`tests/tmp/test_10_video_metadata_completeness_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_10_video_metadata_completeness_phase4.py:116, :118, :134 assert that `video-category` and `video-language` are `hidden is False` after load. Both items start hidden (`initially_hidden=ITEMS`, and `["video-category"]` in case 3). Lines :117, :119 and :135 assert that the `video-category-value` and `video-language-value` text is "Science & Technology", "English" and "Music". Line :120 asserts that the `video-tags` children equal `[{"text": "alpha", "chip": True}, {"text": "beta", "chip": True}]`, and :137 that they equal `[{"text": "solo", "chip": True}]`. - expected: This is what the probe's RIGHT renderer produced when run through this exact RUNNER and `_page`, not a prediction. The RIGHT renderer sets `hidden = !value`, sets `textContent` on the value element, and calls `replaceChildren` with `createElement` + `className = "tag-chip"` + `textContent` chips, which is the plan's `setTaxonomyItem`/`renderTaxonomy` shape. Case 1 reported video-category {hidden: False}, video-category-value {text: 'Science & Technology'}, video-language {hidden: False}, video-language-value {text: 'English'}, and tags [{'text': 'alpha', 'chip': True}, {'text': 'beta', 'chip': True}]. Case 3 reported video-category {hidden: False}, value 'Music', and tags [{'text': 'solo', 'chip': True}]. On today's page each of these ids reads {text: None, hidden: None} and tags reads []. - excludes: Wrong implementation 1: the chips are built with `innerHTML = tags.map(t => `<span class="tag-chip">${t}</span>`).join("")`, markup instead of text chips. The probe's WRONG run shows tags [{'text': '', 'chip': False}], so :120 and :137 go red. Wrong implementation 2: a renderer that never clears the item's `hidden`, such as the HTML's `hidden` attribute left in place. The item then stays at its starting hidden=True, so :116, :118 and :134 go red. Wrong implementation 3: a renderer that writes the value into the item instead of `*-value`. The value element then reads None or '', so :117, :119 and :135 go red. Wrong implementation 4: an off-by-one or a renderer that drops tags. The list comparison at :137 (length 1) and :120 (length 2, in order) catches both.
- C2 - tests/tmp/test_10_video_metadata_completeness_phase4.py:126 and :127 assert that `video-category` and `video-language` are `hidden is True` for a body with `category: ""` and `language: ""`. Both items start visible (`initially_hidden=[]`). Line :128 asserts that the texts of the `video-tags` children equal `["No tags"]`. Line :136 asserts that `video-language` is `hidden is True` in case 3, where the category is non-empty and starts hidden. - expected: This is observed from the probe's RIGHT renderer through this RUNNER. Case 2 reported video-category {hidden: True}, video-language {hidden: True}, and tags [{'text': 'No tags', 'chip': False}], so the child texts are ['No tags']. Case 3 reported video-language {hidden: True} while video-category was {hidden: False}. On today's page the ids read hidden None and tags reads []. - excludes: Wrong implementation 1: category is always shown, e.g. `removeAttribute("hidden")` whatever the value. The probe's WRONG run showed case 2 video-category {hidden: False}, so :126 goes red. Wrong implementation 2: the language item's visibility is keyed on the category's emptiness, a copy-paste slip. WRONG case 3 showed video-language {hidden: False}, so :136 goes red. Case 2 alone cannot tell this apart, because both fields are empty there. Wrong implementation 3: "No tags" is written through `innerHTML` as markup. WRONG case 2 showed tags [{'text': '', 'chip': False}], so :128 goes red. Wrong implementation 4: an empty tag list renders nothing. The child texts are then [], so :128 goes red. Because the items start visible, a renderer that never touches `hidden` also fails :126 and :127.

<assertions>
tests/tmp/test_10_video_metadata_completeness_phase4.py:108 — control: the page requested `/api/video` from the stubbed fetch (every case, via `_page`)
tests/tmp/test_10_video_metadata_completeness_phase4.py:109 — control: `video-title` shows the fixture body's title, so `loadVideo` settled on the server body the taxonomy block reads (every case)
tests/tmp/test_10_video_metadata_completeness_phase4.py:116 — the `video-category` item starts hidden and is not hidden after load — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:117 — `video-category-value` text is "Science & Technology" — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:118 — the `video-language` item starts hidden and is not hidden after load — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:119 — `video-language-value` text is "English" — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:120 — `video-tags` children are exactly two element nodes with class `tag-chip` whose text is "alpha" then "beta", in that order (markup set through innerHTML shows up as a text-less non-chip, so a chip that is not text fails) — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:126 — for an empty category, the `video-category` item starts visible and is hidden after load — C2
tests/tmp/test_10_video_metadata_completeness_phase4.py:127 — for an empty language, the `video-language` item starts visible and is hidden after load — C2
tests/tmp/test_10_video_metadata_completeness_phase4.py:128 — for `tags: []`, the only child of `video-tags` reads "No tags" (a child element or text set through textContent both count) — C2
tests/tmp/test_10_video_metadata_completeness_phase4.py:134 — edge case with a category, an empty language and one tag: the category item starts hidden and is not hidden after load — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:135 — edge case: `video-category-value` text is "Music" — C1
tests/tmp/test_10_video_metadata_completeness_phase4.py:136 — edge case: the language item is hidden on its own, not tied to the category — C2
tests/tmp/test_10_video_metadata_completeness_phase4.py:137 — edge case: `video-tags` holds exactly one `tag-chip` whose text is "solo" (checks the count is not off by one) — C1
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_10_phase4_taxonomy.py", "-s"]. The probe loads the checkpoint's RUNNER, BASE and `_page`, bundles `pages/video-page/index.ts` with the checkpoint's esbuild flags, and runs all three fixture bodies against three things: the current page, a hand-written correct renderer (RIGHT) and a hand-written wrong one (WRONG). What it printed:
- esbuild with `--loader:.css=empty --platform=node` exits 0 and writes a 44.1kb bundle, so the `video.css` import bundles to nothing.
- CURRENT page, every case: requested = ['/api/video', '/recommendations', '/api/v1/config']; video-title text = 'Taxonomy fixture title'. Both controls hold on today's code. The four taxonomy ids report {text: None, hidden: None} and tags = [] because the page never looks them up. So every taxonomy assertion is red today, and it is red because the block is missing, not because the harness broke.
- RIGHT (sets `hidden = !value`, `replaceChildren` with `createElement` `tag-chip` spans, `textContent = "No tags"`), case 1: category/language hidden False with values 'Science & Technology' and 'English'; tags [{alpha, chip True}, {beta, chip True}].
- RIGHT, case 2: category and language hidden True; tags [{'No tags', chip False}].
- RIGHT, case 3: category hidden False with value 'Music'; language hidden True; tags [{solo, chip True}].
- So every assertion passes against a correct renderer, and a `textContent = "No tags"` shows up as the one child.
- WRONG (category always un-hidden, language hidden by the category's emptiness, tags through innerHTML), case 1: tags [{'', chip False}], so line 120 fails.
- WRONG, case 2: category hidden False, so line 126 fails, and tags [{'', False}], so line 128 fails.
- WRONG, case 3: language hidden False, so line 136 fails, and line 137 fails.
I have no delete tool, so `tests/tmp/probe_10_phase4_taxonomy.py` is still on disk and should be removed (it ends in `assert False`).
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_10_video_metadata_completeness_phase4.py` - 8312 characters, inlined in full

```
"""The video page's taxonomy block, run in node with the real page module: it shows the category, language and tags from `/api/video` as text.

- For a body with a category, a language and two tags, the category and language items are shown with the body's values, and the tag list holds one `tag-chip` per tag, in order, whose text is the tag.
- For a body with an empty category, language and tag list, the category and language items are hidden and the tag list's only child reads "No tags".
- For a body with a category, an empty language and one tag, only the language item is hidden and the tag list holds one chip.

The runner stubs the browser platform node lacks: a `document` of recording elements, `window.location`, the storages, and `fetch`, which answers `/api/video` with the case's body and `{}` elsewhere. Each taxonomy item starts in the opposite visibility to the one expected, so the page has to set it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
TITLE = "Taxonomy fixture title"
ITEMS = ["video-category", "video-language"]

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, addEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null,
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? "").join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, insertAdjacentHTML() {}, remove() {},
  };
  return el;
};
const initiallyHidden = JSON.parse(process.env.INITIALLY_HIDDEN);
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div", initiallyHidden.includes(id))); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requested.push(url.pathname);
  const body = url.pathname === "/api/video" ? process.env.VIDEO_BODY : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
await import(process.env.BUNDLE);
// Every stubbed fetch resolves at once, so loadVideo has settled within a few macrotasks.
for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
const report = (id) => ({ text: byId.get(id)?.textContent ?? null, hidden: byId.get(id)?.hidden ?? null });
const ids = ["video-title", "video-category", "video-category-value", "video-language", "video-language-value"];
const tags = (byId.get("video-tags")?.children ?? []).map((c) => ({ text: c.textContent, chip: c.nodeType === 1 && c.classList.contains("tag-chip") }));
process.stdout.write(JSON.stringify({ requested, ...Object.fromEntries(ids.map((id) => [id, report(id)])), tags }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_taxonomy")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path, body: dict, initially_hidden: list[str]) -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "VIDEO_BODY": json.dumps({"videoUuid": "uuid-1", "title": TITLE, **body}), "INITIALLY_HIDDEN": json.dumps(initially_hidden)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page asked /api/video and rendered its body, so the block below saw that body
    assert "/api/video" in page["requested"], page
    assert page["video-title"]["text"] == TITLE, page
    return page


def test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag(bundle):
    page = _page(bundle, {"category": "Science & Technology", "language": "English", "tags": ["alpha", "beta"]}, initially_hidden=ITEMS)

    assert page["video-category"]["hidden"] is False, page  # C1
    assert page["video-category-value"]["text"] == "Science & Technology", page  # C1
    assert page["video-language"]["hidden"] is False, page  # C1
    assert page["video-language-value"]["text"] == "English", page  # C1
    assert page["tags"] == [{"text": "alpha", "chip": True}, {"text": "beta", "chip": True}], page  # C1


def test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags(bundle):
    page = _page(bundle, {"category": "", "language": "", "tags": []}, initially_hidden=[])

    assert page["video-category"]["hidden"] is True, page  # C2
    assert page["video-language"]["hidden"] is True, page  # C2
    assert [child["text"] for child in page["tags"]] == ["No tags"], page  # C2


def test_an_empty_language_alone_hides_only_the_language_item(bundle):
    page = _page(bundle, {"category": "Music", "language": "", "tags": ["solo"]}, initially_hidden=["video-category"])

    assert page["video-category"]["hidden"] is False, page  # C1
    assert page["video-category-value"]["text"] == "Music", page  # C1
    assert page["video-language"]["hidden"] is True, page  # C2
    assert page["tags"] == [{"text": "solo", "chip": True}], page  # C1

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 4 (taxonomy block on the video page) - red (audit round 1)

`tests/tmp/test_10_video_metadata_completeness_phase4.py` exited 1.

```
  tests/tmp/test_10_video_metadata_completeness_phase4.py  3 failed                               0.0s
  -------------------------------------------------------
  total                                                    3 failed                               0.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (taxonomy block on the video page) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All three tests should pass their controls in `_page` (lines 105-109) and then fail on the first taxonomy assertion.
- Line 116 fails as `None is False`. `index.ts` never calls `getElementById("video-category")`, so the runner's `report("video-category")` (runner line 77) gives `hidden: null`.
- Line 126 fails as `None is True`, for the same reason.
- Line 134 fails as `None is False`, for the same reason.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_video_taxonomy.py (NEW). That path does not exist, so it was not read.
2. `code_under_test` lists client/frontend/dist (rebuilt). The test bundles `src/pages/video-page/index.ts` with esbuild and never loads `dist` (lines 88-94), so `dist` was not read.
3. Whether esbuild at `node_modules/.bin/esbuild` and `node` are present was not checked. The prediction assumes both are, and that the `_page` controls pass.
```

Basis for the verdict (not part of the gate record):
- **Anti-pattern pass:** the test fails none of the eight `<how_to_spot>` checks.
  - It never reads a `.md` file and never greps a section or source name.
  - The expected values are written into the test as literals, not re-derived from the code.
  - C2's hidden-state assertions (lines 126-127) sit next to the positive `"No tags"` assertion (line 128) and the `_page` controls (lines 108-109), and `initially_hidden=[]` means the page must set `hidden` itself.
  - The input values are not echoed back to the test untouched: they pass through the page's fetch→render path, and deleting the page's taxonomy code turns every test red.
  - The category is checked at two values ("Science & Technology" and "Music"). Every item starts in the opposite visibility to the one expected, and each `getElementById` stub returns a fresh empty element, so no shipped default can satisfy an assertion.
- **Ladder pass:** the test is at rung 1. It imports the real page module into a stubbed DOM and asserts on the element state it leaves behind. The node subprocess is only there to run TypeScript, not a downshift, so no downshift comment is needed.
- **Stub question:** a stub page fails.
  - An unchanged page fails at lines 116, 126 and 134.
  - Hard-coding "No tags" fails line 120.
  - Hard-coding a category fails line 117 or line 135.
  - Always showing both items fails line 126. Always hiding them fails line 116.
  - Writing tags through `innerHTML` fails line 120, because the runner keeps markup opaque (runner line 41).

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (20 clauses: 6 must_prove, 9 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | with a category, "the block shows the category value" | :116, :117 | the item left hidden (it starts hidden at :114, so the page has to unhide it); a missing or wrong value | CARRIED |
| C1b | must_prove | with a language, "the block shows ... the language value" | :118, :119 | the item left hidden (it starts hidden); a missing or wrong value | CARRIED |
| C1c | must_prove | "one text chip per tag" | :120 | tags joined into one chip, a dropped tag, a reordered list, a child without `tag-chip`, a chip filled through innerHTML (the stub makes that text read as "") | CARRIED |
| C2a | must_prove | with an empty category, "the category ... item [is] hidden" | :126 | a page that never sets visibility (it starts visible, `initially_hidden=[]` at :124) | CARRIED |
| C2b | must_prove | with an empty language, "the ... language item [is] hidden" | :127 | the same, for the language item | CARRIED |
| C2c | must_prove | an empty tag list "reads 'No tags'" | :128 | an empty list, leftover chips, other text, markup written through innerHTML | CARRIED |
| D1 | docstring | "run in node with the real page module" | :109 | a harness that never ran index.ts: the title from the body only appears if the real loadVideo ran | CARRIED |
| D2 | docstring | "shows the category, language and tags from `/api/video` as text" | :108, :117, :119, :120 | values taken from somewhere other than `/api/video` (only that path returns the body); values not written as text | CARRIED |
| D3 | docstring | two tags give "one `tag-chip` per tag, in order, whose text is the tag" | :120 | the wrong order, a missing class, the wrong text | CARRIED |
| D4 | docstring | "category and language items are shown with the body's values" | :116–:119 | items left hidden; the wrong values | CARRIED |
| D5 | docstring | empty body: "category and language items are hidden" | :126, :127 | visibility never set | CARRIED |
| D6 | docstring | "the tag list's only child reads 'No tags'" | :128 | an extra child next to the placeholder (the whole list is compared, so length is checked) | CARRIED |
| D7 | docstring | category, empty language, one tag: "only the language item is hidden" | :134, :136 | hiding both when one field is empty; hiding neither | CARRIED |
| D8 | docstring | "and the tag list holds one chip" | :137 | the "No tags" text or an extra chip | CARRIED |
| D9 | docstring | "Each taxonomy item starts in the opposite visibility to the one expected" | :114, :124, :132 (setup) → :116/:118, :126/:127, :134/:136 | a page that never changes `hidden` passing by default. Checked against each case's `initially_hidden` | CARRIED |
| N1 | name | test 1: "shows both values" | :117, :119 | a missing or wrong value | CARRIED |
| N2 | name | test 1: "one text chip per tag" | :120 | as in C1c | CARRIED |
| N3 | name | test 2: "hides both items" | :126, :127 | visibility never set | CARRIED |
| N4 | name | test 2: "reads no tags" | :128 | as in C2c | CARRIED |
| N5 | name | test 3: "an empty language alone hides only the language item" | :134, :136 | hiding the category too, or not hiding the language item | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. surfaces (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase4.py:63
   `getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div", ...)); ... }`
   The fake `document` creates an element for any id the module asks for. So none of the asserts from :116 to :137 depend on `video-page.html`, which the phase edited and lists in `code_under_test`. The test would still pass if the markup lacked `video-category`, `video-category-value`, `video-language`, `video-language-value` or `video-tags`. The C1 and C2 rows are CARRIED for the module's behaviour. "The block shows" is only proved if the HTML actually has those elements, and this test does not check that. `<surfaces>` says shims belong on the far side of the boundary, and the HTML is changed code, not a severed layer. Whether this matters depends on the seam the phase's `<checkpoint>` names, and that seam was not supplied (see NOT ASSESSED).
2. bounds (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase4.py:124
   The only "absent" input tested is the empty string or empty list. These cases never run: `category`/`language`/`tags` missing from the body, `null` values, a non-array `tags`, a non-string tag, a whitespace-only category, and an empty category with a language present (the mirror of test 3 at :132).
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_10_video_metadata_completeness_phase4.py:71
   The fake `fetch` always returns 200 for `/api/video`. Nothing tests what the taxonomy block shows when that call fails or returns non-JSON, which is when the page falls back to the instance metadata (`fetchVideoMetadataFromInstance`, index.ts:560).

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists client/frontend/src/pages/video-page/index.ts, client/frontend/video-page.html and client/frontend/src/video.css as EDITED. As read, none of them contains `video-category`, `video-language`, `video-tags`, `tag-chip`, "No tags", or any read of `category`/`language`/`tags` from the body; a Grep for those words across client/frontend (excluding node_modules) matched nothing. I could not see which inputs the code accepts, so I judged bounds and the failure path from the test and `must_prove` alone.
2. tests/active/test_frontend_video_taxonomy.py is listed in `code_under_test` as NEW but does not exist, so I could not read it.
3. client/frontend/dist was not read. The test builds its own bundle from src (:89), so dist is not part of what the test exercises.
4. The seam named by the phase's `<checkpoint>` was not supplied. Without it I could not settle whether the fake `document` at :61–:66 is a legitimate shim for this checkpoint (Recommendation 1).

## 2026-09-27 - Step 7 - Phase 4 (taxonomy block on the video page) - checkpoint outcome (run 1)

`tests/tmp/test_10_video_metadata_completeness_phase4.py` exited 0 after the phase landed.

<changes>
### client/frontend/src/pages/video-page/index.ts
- Added lookups for the new elements: `video-category`, `video-category-value`, `video-language`, `video-language-value` and `video-tags`.
- `VideoMetadata` has three new fields: `category?: string`, `language?: string` and `tags?: string[]`.
- `fetchVideoMetadataFromServer` reads `category` and `language` from the `/api/video` body, and uses `""` when either is missing. It reads `tags` only if it is an array, and keeps only the string entries; otherwise it uses `[]`.
- `loadVideo` fills in the block using a new helper, `renderTaxonomyItem(itemEl, valueEl, value)`. It hides the item when the value is empty and sets the value as text. The tag list gets one `<span class="tag-chip">` per tag through `replaceChildren`, with each chip's text set as text. With no tags, the list's text is set to "No tags". Nothing goes through `innerHTML`, because tags come from remote instances.
- Not done: the PeerTube instance fallback (`fetchVideoMetadataFromInstance`) does not map `category`, `language` or `tags`. Phase 4 is limited to `/api/video`. When the page falls back to the instance, both items stay hidden and the tag list reads "No tags".

### client/frontend/video-page.html
- Added `<dl id="video-taxonomy" class="video-taxonomy">` between `video-meta-row` and `video-description`. It has three `taxonomy-item` rows:
  - Category: `#video-category` holding `dd#video-category-value`
  - Language: `#video-language` holding `dd#video-language-value`
  - Tags: `dd#video-tags.tag-list`
- The category and language rows start `hidden`, so they don't show as empty labels before the metadata arrives.

### client/frontend/src/video.css
- New rules for `.video-taxonomy`, `.taxonomy-item` and its `dt`/`dd`, `.tag-list` and `.tag-chip`. The chips are pill-shaped like the existing `.instance-meta` chips.
- Added `.taxonomy-item[hidden] { display: none; }`. Without it, the flex display on `.taxonomy-item` would override the `hidden` attribute.

### client/frontend/dist
- **Not rebuilt.** I have no shell, so I couldn't run `npm run build` or delete the old hashed `video-*.js` / `video-*.css` files it replaces. The checkpoint builds its own bundle from `src` with esbuild and doesn't read `dist`, so it isn't affected. As agreed at Step 6, the operator still needs to run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before the merge.

### tests/active/test_frontend_video_taxonomy.py
- Not created by me. The checkpoint is `tests/tmp/test_10_video_metadata_completeness_phase4.py`, and I assume the workflow moves it to this path. I left it untouched.

### Observation
- A probe (`tests/tmp/probe_10_phase4_impl.py`) built the edited `index.ts` with the checkpoint's own esbuild command and ran it under the checkpoint's runner. Results:
  - **Body 1:** category and language showing with "Science & Technology" and "English"; tags `alpha` and `beta` as `tag-chip`s.
  - **Empty body:** both items hidden; the only child of the tag list is "No tags".
  - **Music body:** only the language item hidden; one `solo` chip.
- In all three cases the control fields matched: `/api/video` was requested and the title was rendered.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_10_phase4_impl.py - my throwaway probe (see changes). I have no tool that deletes files, so it's still there and needs removing by hand.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_10_video_metadata_completeness_phase4.py  3 passed                               0.0s
  -------------------------------------------------------
  total                                                    3 passed                               0.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_10_video_metadata_completeness_phase4.py`

## 2026-09-27 - Step 8 - refactor pass

<refactors>
none - I read all four phases' production code (schema.sql, db.ts, videos-worker.ts, both dist files, whitelist_migrations.py, sync-whitelist.py, peertube_labels.py, handlers/video.py, video-page.html, index.ts, video.css) and found nothing in this build's changes worth consolidating without changing behaviour, so I edited no file.
</refactors>

<left_out>
Merging `migrateVideosLanguage` into `migrateVideos` (db.ts), and `migrate_videos_language` into `migrate_videos_schema` (whitelist_migrations.py): left out because both paths are needed. The rebuild only fires when the error columns are missing, so a table that already has them but lacks `language` can only get it from the ALTER. Folding them together would change which DBs get migrated.
Reading `extract_language`/`extractLanguage` and `category_label`/`language_label` from one shared place: left out because they live on opposite sides of the TS/Python boundary, and each already matches the style of its file.
Pulling the tag-chip rendering in `loadVideo` (index.ts) into its own helper next to `renderTaxonomyItem`: left out because it would be cosmetic only, with one call site and no second user.
The pre-existing duplication in videos-worker.ts (`groupByInstance`/`groupByInstanceTags`/`groupByInstanceComments`, `processTagInstance`/`processCommentsInstance`) and the `DEPRECATED_*` migration scaffolding in db.ts: left out because this build did not write them, and changing them would grow the build past what was approved.
engine/crawler/dist/db.js and dist/videos-worker.js: these are still hand-edited rather than tsc output, and I can't run a shell to rebuild them. The operator should run `cd engine/crawler && npm install && npm run build` and review the dist diff before commit.
client/frontend/dist: still not rebuilt (phase 4 had the same limit). The operator should run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before merge.
The probes this build left in tests/tmp: probe_10_dist_language.py (emptied), probe_10_phase4_impl.py, probe_10_phase4_taxonomy.py, probe_10_phase3_channels.py, probe_10_phase3_refresh.py, probe_10_phase2_shape.py, probe_10_phase2_labels.py, probe_10_crawl.py and probe_10_language.py. I have no delete tool, so the operator needs to remove them.
The step's "What the pass is measured against" section reached me as an unfilled `{rat_tail_rules}` placeholder. I measured against the role's rules instead: the build's only deliberate simplification, the stock label lists in peertube_labels.py, already has a `rat-tail:` comment naming the ceiling and the upgrade path.
</left_out>

<needs_fresh_red>
none - mapping category, language and tags in the video page's PeerTube-instance fallback (`fetchVideoMetadataFromInstance`) would be new behaviour, but phase 4 left it out of scope on purpose, so it belongs on the roadmap if wanted, not in this pass.
</needs_fresh_red>

<observation>
From reading the code (nothing was run, and no file changed): the landed code needs no refactor, and the unbuilt dist output plus the leftover tests/tmp probes are the only loose ends, both for the operator.
</observation>

## 2026-09-27 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 3 of 23 test groups (20 unchanged):
  test_host_normalisation.py — changed
  test_search_fusion.py — no map entry
  test_videos_worker.py — changed
  test_host_normalisation.py  19 passed                              0.1s
  test_search_fusion.py       10 passed                              2.1s
  test_videos_worker.py       1 passed                               1.1s
  --------------------------
  total                       30 passed                              2.3s wall, 3 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 9 - document triage

- [ ] `DATA_BUILD.md` - The build adds `videos.language` to both producers. Section 1 (crawl) needs a sentence saying the crawler stores each video's PeerTube language code in `videos.language`, and that any crawler command opening an existing `crawl.db` adds the column (`migrateVideosLanguage` in `db.ts`). Section 2 (sync) needs two notes. First, `sync-whitelist.py` refuses a `crawl.db` the crawler has not opened since the change (the superset check). Second, it refuses an existing `whitelist.db` until `migrate-whitelist.py` has added `language` (the exact check). Beside the `migrate-whitelist.py` block (around line 157), add the upgrade order: merge; open or run the crawler once on `crawl.db`; run `migrate-whitelist.py` on every `whitelist.db`, prod included; restart the Engine. Also state that `run-dataset-build.sh` does not migrate on its own, and that `/api/video` refreshes written to `whitelist.db` are replaced by the next sync (`rebuild_content_tables` reloads from `crawl.db`).
- [ ] `engine/server/README.md` - Line 9 reads only "`/api/video` metadata for the video page", which no longer describes the route. It should say the following. One fetch of `/api/v1/videos/{id}` from the source instance refreshes the stored title, description, stats, tags, category, language, nsfw, duration and thumbnail. A write happens only when that fetch returns a JSON object. A failed, unreachable or malformed source leaves the DB untouched (`last_checked_at` and `instances.last_error` included), and the response is built from the DB row. The response adds `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`. Category and language are shown as PeerTube's default labels (`data/peertube_labels.py`), with the raw id or code when no default label exists. The Engine needs a `whitelist.db` migrated with `migrate-whitelist.py` (`language` column), or `/api/video` fails with `no such column: v.language`.
- [ ] `DEPLOYMENT.md` - Line 374-375 says `/api/video` makes live calls per request. Add that the route writes the refreshed metadata back to `whitelist.db` only when the source answers with a valid video object inside the request's statement deadline (5 s by default). A slower source is still answered with fresh values but nothing is stored. Add an upgrade note or a Triage row for this deploy: run `migrate-whitelist.py` on the Engine's `whitelist.db` before restarting the Engine. If that is skipped, every video page silently falls back to direct-instance metadata, the Client proxy logs 502 `ENGINE_PROXY_UNAVAILABLE` on `/api/video`, and the Engine journal shows `no such column: v.language`.
- [ ] `docs/project/roadmap.md` - Implementation-order step 2 (line 142) reads "feed panel I1 and I2, then I3 … Landing I1 before any further crawl avoids a second full re-crawl." That is out of date: the language capture part of I1 is delivered. The crawler and `/api/video` store the PeerTube language code in `videos.language`, and labels resolve at read time through `engine/server/data/peertube_labels.py`. Rewrite the step to name what remains: label storage only if it is still wanted, the I2 filter, and the I3 backfill. Note that existing rows get a language only from a full re-crawl, since `--new-videos` and INSERT_ONLY merges skip existing rows, or from video-page views in `whitelist.db`, which the next sync discards.
- [ ] `docs/project/plans/archive/04-feed-parameter-panel.md` - I1 (line 19-20) and acceptance item 1 (line 47) specify new `language_id` and `language_label` columns. The `videos` table now already has `language` (code only) in `engine/crawler/schema.sql`, the whitelist schema and the migration, and the crawler already captures it in `toVideoRow`. Record this against I1 so a future I1 build does not add a duplicate column: the column is `language` rather than `language_id`, the capture is delivered, and labels come from `engine/server/data/peertube_labels.py` at read time. Line 40 (backfill) and R1 (sparse data) stay valid.
- [ ] `docs/project/plans/18-english-subtitles.md` - Three statements are now false. Line 20 says the `videos` table "stores no language". Line 43 lists "adding a `language` column to the crawl" as out of scope, which is now done by another build. Line 90 says there is "no language column to select by". Update them to say that `videos.language` holds the PeerTube language code, filled by the crawler for newly crawled videos and by `/api/video` views. Coverage for existing rows is sparse until a re-crawl or backfill.
- [ ] `docs/project/issues/10-video-metadata-completeness.md` - This is the issue the build delivers, so it is done at harvest on main. Set `Status: enhancement, complete` and append a delivery comment. The comment records the accepted limits:
- labels come from PeerTube defaults only (plugin or renamed entries show the raw id or code);
- PeerTube's unset category shows as "Unknown";
- language and description removals at the source do not propagate (null or empty keeps the DB value);
- persistence is best-effort under the 5 s statement deadline;
- refreshes in `whitelist.db` are lost at the next sync;
- the video page's instance-direct fallback (`fetchVideoMetadataFromInstance`) does not show category, language or tags, which diverges from R6.

Then move the file to `docs/project/issues/archive/`.

Out of scope:
- [ ] `docs/project/issues/14-collapsible-description.md` - Nothing it claims is false. It describes the `video-description` behaviour, which this build did not change. The new `video-taxonomy` block between `video-meta-row` and `video-description` only affects merges: expect a conflict at harvest when both touch the adjacent markup, CSS and `loadVideo` fill code. That is a note for the merge, not a document edit.
- [ ] `README.md` - It mentions `/api/video` only as a public route (line 46-48) and as a smoke check expecting 200 through the Client proxy (line 134). Both are still true once the whitelist DB is migrated. It says nothing about what the route returns or refreshes.
- [ ] `client/README.md` - It lists `/api/video` only as a read-gateway route (line 37). The proxy still passes the body through unchanged, so the line stays accurate.
- [ ] `client/frontend/README.md` - It says the frontend fetches `/api/video` and renders the video page (lines 8-9), without listing which metadata the page shows. Nothing there is made false by the new taxonomy block.

ADR conflicts: none - there is no `docs/project/adr/` directory or any ADR file in this worktree, and no `docs/wiki/` either, so no ADR covers the area this build touched.

## 2026-09-27 - Step 9 - Update documentation

- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md: added `videos.language` to the crawl and sync sections, plus the schema checks and upgrade order for sync.
- [x] `engine/server/README.md` - updated: I rewrote the `/api/video` bullet in `engine/server/README.md` so it describes what the route does now: it refreshes from the source instance, writes to the DB only when the fetch succeeds, returns six new keys, shows category and language as labels, and needs the `language` migration.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: `/api/video` write-back conditions, a whitelist migration note, and a Triage row for an unmigrated `whitelist.db`
- [x] `docs/project/roadmap.md` - updated: roadmap.md: rewrote Implementation-order step 2 (Language) around what remains now that language capture is in, and fixed the stale feed-panel plan path.
- [x] `docs/project/plans/archive/04-feed-parameter-panel.md` - updated: Recorded in the plan that I1's language column and crawler capture already exist, as `language` (the code only, no label column), so a later I1 build won't add `language_id`/`language_label` twice.
- [x] `docs/project/plans/18-english-subtitles.md` - updated: Corrected the three statements in the subtitles plan that said the `videos` table has no language column.
- [x] `docs/project/issues/10-video-metadata-completeness.md` - updated: Closed issue 10 as delivered: the status is now `enhancement, complete`, a Delivered comment lists the accepted limits, and the file is written to `docs/project/issues/archive/`. The original at `docs/project/issues/10-video-metadata-completeness.md` is still there because I have no tool that can delete a file. Please `git rm` it.
- [x] `docs/project/issues/14-collapsible-description.md` - out of scope: Nothing it claims is false. It describes the `video-description` behaviour, which this build did not change. The new `video-taxonomy` block between `video-meta-row` and `video-description` only affects merges: expect a conflict at harvest when both touch the adjacent markup, CSS and `loadVideo` fill code. That is a note for the merge, not a document edit.
- [x] `README.md` - out of scope: It mentions `/api/video` only as a public route (line 46-48) and as a smoke check expecting 200 through the Client proxy (line 134). Both are still true once the whitelist DB is migrated. It says nothing about what the route returns or refreshes.
- [x] `client/README.md` - out of scope: It lists `/api/video` only as a read-gateway route (line 37). The proxy still passes the body through unchanged, so the line stays accurate.
- [x] `client/frontend/README.md` - out of scope: It says the frontend fetches `/api/video` and renders the video page (lines 8-9), without listing which metadata the page shows. Nothing there is made false by the new taxonomy block.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/10-video-metadata-completeness.md`: docs/project/issues/10-video-metadata-completeness.md - the original of the moved file is still there because I have no tool that can delete a file; remove it with `git rm` so the only copy is the one in `docs/project/issues/archive/`.

**ADR conflicts.** none - there is no `docs/project/adr/` directory or any ADR file in this worktree, and no `docs/wiki/` either, so no ADR covers the area this build touched.

### `DATA_BUILD.md`

<changes>
DATA_BUILD.md: added `videos.language` to the crawl and sync sections, plus the schema checks and upgrade order for sync.

- **Section 1, Video crawl:** the crawler stores each video's PeerTube language code in `videos.language`, and stores NULL when the payload has no language or a null id. Any crawler command that opens an existing `crawl.db` adds the column (`migrateVideosLanguage` in `db.ts`). Rows already in the table stay NULL until a video crawl without `--new-videos` visits them again.
- **Section 2, sync:** a new list of the checks `sync-whitelist.py` runs before copying:
  - the superset check refuses a `crawl.db` that no crawler command has opened since the change;
  - the exact check (schema plus `popularity`) refuses an outdated existing `whitelist.db` and points to `migrate-whitelist.py`;
  - a new `whitelist.db` is created with the current schema.
- **Next to the `migrate-whitelist.py` block:**
  - The migration only adds columns: rows, `videos_fts` and its triggers are left alone, and running it again does nothing.
  - `scripts/run-dataset-build.sh` does not migrate on its own.
  - The upgrade order: merge; run the crawler once on `crawl.db`; migrate every `whitelist.db`, prod included; restart the Engine. What an unmigrated DB does to `/api/video` is covered in `engine/server/README.md`, and this document points there.
  - `/api/video` refreshes are lost at the next sync, because `rebuild_content_tables` deletes `videos` and reloads it from `crawl.db`.

Checked against the code: `applyBaseSchema` in `db.ts`, `ensure_schema_compatibility` and `rebuild_content_tables` in `sync-whitelist.py`, the `language` ALTER in `whitelist_migrations.py`, `migrate-whitelist.py` calling `migrate_whitelist_schema`, and `scripts/run-dataset-build.sh`, which only calls `sync-whitelist.py`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/README.md`

<changes>
I rewrote the `/api/video` bullet in `engine/server/README.md` so it describes what the route does now: it refreshes from the source instance, writes to the DB only when the fetch succeeds, returns six new keys, shows category and language as labels, and needs the `language` migration.

I checked it against `engine/server/api/handlers/video.py`. The bullet now says:
- Each request fetches `/api/v1/videos/{id}` and refreshes the stored title, description, stats, tags, category, language, nsfw, duration and thumbnail. A field the source leaves absent, null or invalid keeps its DB value.
- The DB is written only when the fetch returns a JSON object. If the source fails, can't be reached or sends a malformed body, nothing is written (including `last_checked_at` and `instances.last_error`) and the response is built from the DB row.
- The response adds `tags`, `category`, `language`, `nsfw`, `duration` and `thumbnailUrl`, with their types.
- Category and language are stored as ids and codes but returned as PeerTube's default labels from `data/peertube_labels.py`, or as the raw value when there is no default label.
- The route needs a `whitelist.db` migrated with `db/jobs/migrate-whitelist.py`. Without that, requests fail with `no such column: v.language`. The upgrade order is not repeated here; the bullet points to `DATA_BUILD.md`, which owns it.

I left out the 5 s statement deadline because `DEPLOYMENT.md` owns it. I also didn't give a status code for the unmigrated-DB failure: the handler doesn't catch that error, so the bullet names only the error text.

**Open point:** the intro line still calls the Engine a "Read-only Engine API", but `/api/video` writes to `whitelist.db`. I didn't change that line because the triage didn't ask for it.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `DEPLOYMENT.md`

<changes>
DEPLOYMENT.md: `/api/video` write-back conditions, a whitelist migration note, and a Triage row for an unmigrated `whitelist.db`

- **Section 1 (Prepare the database):** new paragraph. An existing `whitelist.db` must be migrated with `migrate-whitelist.py` before the Engine starts on newer code, or `/api/video` fails. It points to Triage for the symptom and to `DATA_BUILD.md` for the upgrade order, without repeating the steps.
- **Section 6, Firewall:** the "Outbound 443" paragraph is now one line, and a new paragraph follows it:
  - `/api/video` writes refreshed metadata back to `whitelist.db` only when the source answers with a valid video object.
  - The write shares the request's statement deadline (5 s by default, `DEFAULT_STATEMENT_TIMEOUT_SECONDS`), and time spent waiting on the source counts against it.
  - When a slow source uses up the deadline, the page still gets fresh values, the write can be interrupted, and the Engine logs `[video] failed to persist dynamic metadata`.
- **Section 2, Triage:** new row for a `whitelist.db` that was not migrated. Symptom: video pages lose category, language and tags; the Client logs `engine.proxy` 502 on `/api/video`; the Engine journal shows `no such column: v.language`. The page falls back to reading the source instance directly. Fix: run `migrate-whitelist.py`, then restart the Engine.

**Two places where the doc is worded differently from the checklist, based on the code:**
- **Deadline wording.** The checklist said a slower source means "nothing is stored". The deadline (`data/db.py`) works through SQLite's progress handler, which only checks every 10,000 instructions. So I wrote that the write *can be* interrupted, and named the log line the handler writes when that happens (`video.py`, `except sqlite3.OperationalError`).
- **502 code not named.** The checklist named `ENGINE_PROXY_UNAVAILABLE`. On a missing column, `do_GET` re-raises the non-interrupt `OperationalError` and the Engine closes the connection with no response. urllib does not wrap the resulting `RemoteDisconnected` in `URLError`, so the Client's proxy should land in its generic `except Exception` branch: `ENGINE_PROXY_FAILURE`, ERROR "proxy request exception". This comes from reading the code, not from a run, so the row says only "`engine.proxy` 502" and does not name a code.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
roadmap.md: rewrote Implementation-order step 2 (Language) around what remains now that language capture is in, and fixed the stale feed-panel plan path.

- **Step 2** keeps three items and drops the old "land I1 before any further crawl" constraint:
  - I1's remainder: stored labels, only if still wanted. The step also says that `videos.language` already holds the PeerTube language code, filled by the crawler and by `/api/video`, and that labels are looked up at read time through `engine/server/data/peertube_labels.py`.
  - I2: the filter.
  - I3: the backfill.
- **How existing rows get a language:** only from a full re-crawl, because `--new-videos` and the `INSERT_ONLY` videos merge skip rows that already exist. Video-page views also set it, but they write to `whitelist.db` and the next sync discards that. The sync behaviour is pointed at `DATA_BUILD.md` rather than repeated.
- **Code checked:** `merge_rules.json` has videos as `INSERT_ONLY`; `updater-worker.py` uses `--new-videos`; `toVideoRow` sets `language`; `handlers/video.py` writes `language`.
- **Path fix (in this same file):** the M4 line F4-M4 linked `docs/project/plans/04-feed-parameter-panel.md`, but that file is at `docs/project/plans/archive/04-feed-parameter-panel.md`. The link now points there.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/plans/archive/04-feed-parameter-panel.md`

<changes>
Recorded in the plan that I1's language column and crawler capture already exist, as `language` (the code only, no label column), so a later I1 build won't add `language_id`/`language_label` twice.

I checked each claim against the code before writing it: `schema.sql`, `sync-whitelist.py`, `migrate_videos_language` in `whitelist_migrations.py`, `extractLanguage` and `extractCategory` in `videos-worker.ts`, `extract_language` in `handlers/video.py`, and `data/peertube_labels.py`.

- **Status line:** says I1's column and capture are delivered, points to `docs/project/issues/archive/10-video-metadata-completeness.md` (where that issue will sit after harvest), and refers to C1 for the details.
- **C1:** the two bullets that asked for `language_id`/`language_label` are now one "Delivered: column and capture" bullet. It covers:
  - the nullable `language TEXT` column holding the PeerTube code, and the three places that create it;
  - `toVideoRow`/`extractLanguage` filling it, and the shape of PeerTube's `{id, label}` payload;
  - no label column, because labels resolve when read through `engine/server/data/peertube_labels.py`;
  - an explicit line that I1 adds no `language_id` or `language_label` column.

  I dropped "lowercase" because codes like `zh-Hans` are stored as they come.
- **Acceptance 1–2:** now name the `language` column, and each is marked as met by what was delivered.
- **Consistency constraints:** the bullet that put the normalisation helper in `host-filters.ts` was wrong. It now names `extractLanguage` in `videos-worker.ts` (beside `extractCategory`) and the Engine's `extract_language` in `handlers/video.py` as the code to reuse.
- **Conflicts R4:** the mismatch is now about C1's filtering (I2) changing the Engine, because the capture half is already done.
- **Approach I1:** marked delivered, pointing to C1. I removed the "land before a crawl to avoid a re-crawl" advice, since it no longer applies.
- **Rollback notes:** the backfill writes only `videos.language`.
- I left the backfill (Out of scope, I3) and R1 (sparse data) unchanged; both still hold.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/plans/18-english-subtitles.md`

<changes>
Corrected the three statements in the subtitles plan that said the `videos` table has no language column.

- **What the current code does → Language data:** this bullet used to say the table "stores no language". It now says the table stores `duration` and `language` (the PeerTube language code). The crawler fills `language` for the videos it crawls. `/api/video` fills it in `whitelist.db` when a video page is viewed, and the next sync overwrites that from `crawl.db`. Rows crawled before the column existed stay empty until a full re-crawl or a backfill, so coverage is sparse. I checked this against `engine/crawler/schema.sql:43` (the column), `videos-worker.ts:700` (`extractLanguage`) and `handlers/video.py:298/361` (the merge and the UPDATE). Line `schema.sql:29` is still the `CREATE TABLE videos` line.
- **Scope → Out of scope:** "adding a `language` column to the crawl" is already delivered, so I replaced it with "backfilling `videos.language` for rows crawled before the column existed". That is the crawl-side language work still left, and it keeps the plan's intent of not doing corpus-wide language work. **Decision for you:** this is a new out-of-scope item rather than a plain deletion, so check that it matches what you want.
- **Alternatives considered → Batch generation:** "no language column to select by" now reads "`videos.language` empty for most existing rows".
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/10-video-metadata-completeness.md`

<changes>
Closed issue 10 as delivered: the status is now `enhancement, complete`, a Delivered comment lists the accepted limits, and the file is written to `docs/project/issues/archive/`. The original at `docs/project/issues/10-video-metadata-completeness.md` is still there because I have no tool that can delete a file. Please `git rm` it.

- The `Status:` line reads `enhancement, complete`. The Problem, Proposed solution and Validation sections are unchanged.
- There is a new `### Delivered` comment under `## Comments`, in the same style as archived issue 34. It covers:
  - **What was delivered:**
    - `/api/video` only writes to the database when the source instance returns a JSON object. When the instance fails, no UPDATE runs at all.
    - `videos.language` exists in both producers.
    - Category and language labels come from `engine/server/data/peertube_labels.py`, and the database keeps the raw ids and codes.
    - The `video-taxonomy` block is on the video page.
    - The checkpoint tests in `tests/tmp`.
  - **Where the details live:** it points to the plan, to `engine/server/README.md` for how the route behaves, and to `DATA_BUILD.md` for the upgrade order, without repeating them.
  - **Accepted limits:**
    - Labels come from PeerTube's defaults only.
    - An unset category shows as "Unknown".
    - Removing a language or description at the source does not carry over.
    - Saving is best-effort under the 5 s statement deadline.
    - Stored refreshes are replaced at the next sync.
    - The instance-direct fallback on the video page does not show category, language or tags, which differs from R6.
  - **Still owed on main:** the crawler dist and the frontend dist both need rebuilding, and the video page still needs its manual check.
- I checked these points against the code:
  - The success guard (`dynamic is not None`) is in `video.py`.
  - A null language id or an empty description keeps the value already in the database (`pick_text`).
  - An unset category is stored as "Unknown" because the label is picked before the id.
  - `/api/video` runs inside the `do_GET` `_statement_deadline()`, whose default is `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0`. A write that runs past it raises `OperationalError`, which is caught and logged.
  - `fetchVideoMetadataFromInstance` does not map category, language or tags.
</changes>

<not_on_checklist>
docs/project/issues/10-video-metadata-completeness.md - the original of the moved file is still there because I have no tool that can delete a file; remove it with `git rm` so the only copy is the one in `docs/project/issues/archive/`.
</not_on_checklist>

## 2026-09-27 - Step 10 - Harvest tests

<moved>
None. The harvest stopped at Step 4 because the operator dismissed the approval question without answering. Nothing was moved. All four scope files are still in tests/tmp: test_10_video_metadata_completeness_phase1.py, _phase2.py, _phase3.py and _phase4.py. The plan that was put to the operator (all 15 test functions DURABLE) is in docs/project/plans/harvest-10-video-metadata-completeness-plan.md: phase1 migration test → new tests/active/test_whitelist_migrations.py; phase1's two crawl tests → tests/active/test_videos_worker.py; phase2+phase3 handler tests → new tests/active/test_video.py; phase4's three taxonomy tests → new tests/active/test_frontend_video_page.py.
</moved>

<retired>
none
</retired>

<group_map>
none. test_groups in .un/skills/devsecops/config.json was not edited because the plan was not approved. The proposed changes, not applied, were: add test_whitelist_migrations.py, test_video.py and test_frontend_video_page.py, and add engine/crawler/src/db.ts and dist/db.js to test_videos_worker.py.
</group_map>

<mutations>
none. No mutation ran and no production file was touched, because no test moved. validate_tests.py was run only with --show-config.
</mutations>

<cleared>
Nothing. delete_me/ was not created and holds nothing. tests/tmp still holds the 4 in-scope files and the out-of-scope probe_*.py files. The record snapshot was byte-identical to tests/last_test_validation.json (checked with cmp), so it was moved back and the record is unchanged. Final counts: 0 moved, 0 retired, 0 mutations, 0 cleared. The harvest needs to be re-run from Step 1 once the operator approves.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: ['tests/tmp/test_10_video_metadata_completeness_phase4.py', 'tests/tmp/test_10_video_metadata_completeness_phase3.py', 'tests/tmp/test_10_video_metadata_completeness_phase2.py', 'tests/tmp/test_10_video_metadata_completeness_phase1.py']

`--compare` exited 0.

```
selected 1 of 23 test groups (22 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.3s
  ---------------------
  total                  10 passed                              2.5s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

