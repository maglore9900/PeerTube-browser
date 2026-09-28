# Build record - 16-popular-weighted-random

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/20-16-popular-weighted-random.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Popular feed: weighted random by similarity\n\nStatus: enhancement, needs-triage\nOrigin: task 12a, [M3][F2] (marker was wrong in the old tracker: this is feed work, not API versioning)\n\n## Problem\n\nWhen likes exist, popular is sorted by similarity, but then a random sample is taken from the whole pool, so the sorting barely affects the result.\n\n## Proposed solution\n\nReplace `random.sample` with weighted random using similarity as the weight.\n\n- After scoring, compute weights (e.g. `max(similarity, 0.0)` or `similarity ** alpha`).\n- Pick candidates by weighted sampling without replacement (optionally with a small epsilon for diversity).\n- Config parameter `popular.weighted_random_alpha` (0 = disabled).\n- Empty/zero weights fall back to plain random.\n\n## Related\n\n- Land before `17-feed-modes`, which exposes popular as a user-facing mode.\n\n## Comments",
  "request_source": "read from docs/project/issues/16-popular-weighted-random.md",
  "slug": "16-popular-weighted-random",
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
      "name": "Similarity-weighted popular draw",
      "checkpoint": "Seam: the public `PopularVideosGenerator.get_candidates(server, user_id, limit, config=...)`. It is driven with stub `PopularVideosDeps`: a fixed pool that ignores `count`, one like `[1, 0]`, and 2-D vectors `[s, sqrt(1-s\u00b2)]` so each cosine is exactly `s`. The caps are 0 and the server is a `SimpleNamespace(db=None, db_lock=threading.Lock())`. Harness: `tests/active/test_popular_weighted_random.py` runs every case in one Engine-interpreter child (`ENGINE_PY -c _CHILD SERVER_DIR CASES_JSON`, `sys.path[:0] = [server, server + \"/api\"]`), which reseeds `random` per trial with a string seed and reports JSON. This follows the existing ENGINE_PY child precedent in `test_search_fusion.py` and `test_internal_client_reads.py`; that route is needed because the pytest interpreter lacks numpy. Asserts for clause_1: skew (10 hi at 0.9 vs 10 lo at 0.1, alpha 1, 400 trials): every draw has `limit` distinct ids, and hi hits \u2265 3 \u00d7 lo hits. zero_fill (3 positive, 7 zero-weight including negative and missing-embedding, limit 5): all 3 positives are in every draw, and across trials the fill covers every zero-weight id. zero_unused (6 positive, 10 zero): no zero-weight id ever appears. Asserts for clause_2: all_zero and the five disabled configs (key missing, None, 0, -1.0, NaN) each equal `random.sample(ordered, limit)` recomputed under the same seed. In the disabled cases `popular_videos._weighted_from_pool` is replaced by a function that raises, so taking the wrong branch fails the fixture's return-code assert. Regression guard: pools of exactly `limit` and fewer than `limit` come back whole.",
      "intent": "`PopularVideosGenerator.get_candidates` in `popular_videos.py` ends its likes path in a new `_weighted_from_pool` draw that favours candidates closer to the likes whenever `weighted_random_alpha` is positive (1.0 in the `home` and `upnext` profiles), and ends it in today's uniform `_random_from_pool` sample otherwise.",
      "clauses": [
        {
          "id": "C1",
          "text": "With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`."
        },
        {
          "id": "C2",
          "text": "With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed."
        }
      ],
      "files": [
        "engine/server/api/recommendations/candidates/popular_videos.py (EDITED)",
        "engine/server/api/server_config.py (EDITED)",
        "tests/active/test_popular_weighted_random.py (NEW)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/recommendations/candidates/popular_videos.py`\n- `get_candidates` reads `weighted_random_alpha` from the per-generator config as `float(config.get(\"weighted_random_alpha\") or 0.0)`. If the value is positive, the end of the likes path now calls the new `_weighted_from_pool(scored, limit, alpha)`. If it is missing, None, 0, negative or NaN (`not alpha > 0` also catches NaN), the path does exactly what it did before: `_random_from_pool(ordered, limit)` over the pool sorted by similarity. The early returns for no likes, missing embeddings and no usable liked vectors are unchanged and still draw uniformly.\n- New `_weighted_from_pool`:\n  - Each candidate's weight is `similarity ** alpha`, or 0.0 if its clamped similarity is not positive.\n  - Candidates are split on the weight, not the score, so a tiny score that underflows to 0 under a large alpha can't cause a divide-by-zero.\n  - If no weight is positive, it hands the same similarity-ordered list to `_random_from_pool`. It uses no randomness before that, so the result is exactly the uniform sample under the same seed.\n  - A pool of `limit` or fewer comes back whole.\n  - Otherwise it runs an Efraimidis-Spirakis draw without replacement over the positive-weight candidates, keyed on `log(1 - u) / w` (the log form avoids `u ** (1/w)` underflowing to ties) and keeps the top `limit` keys.\n  - If there are fewer positive-weight candidates than `limit`, the gap is filled with `random.sample` over all zero-weight candidates.\n- Added `import math`.\n\n### `engine/server/api/server_config.py`\n- Added `\"weighted_random_alpha\": 1.0` to the `popular` generator in the `home` and `upnext` profiles, with a one-line comment on the `home` entry. `guest_home` and `guest_upnext` are unchanged; guests have no likes, so they would never reach the weighted path anyway.\n\n### `tests/active/test_popular_weighted_random.py`\n- I didn't write this file. The phase lists it as NEW, but the gating checkpoint is `tests/tmp/test_16_popular_weighted_random_phase1.py`, and I didn't touch that either. Presumably the workflow moves it into place later."
    }
  ],
  "digests": {
    "tests/tmp/test_16_popular_weighted_random_phase1.py": "4cded4b69edc6d55428b4dc29e21deed5f867571fafb0734221f6d08e3094fa2"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260928T172131-f19d-dev-flow"
  ],
  "plan": "docs/project/plans/20-16-popular-weighted-random.md",
  "record": "docs/project/plans/20-16-popular-weighted-random.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nWhen a visitor has likes, the popular layer of the recommendation feed should favour popular videos that are similar to what the visitor liked. Today `PopularVideosGenerator.get_candidates` (`engine/server/api/recommendations/candidates/popular_videos.py`) scores every pool entry by its maximum cosine similarity to the liked vectors and sorts by it. It then calls `_random_from_pool`, which does `random.sample` over the whole pool, so the similarity scoring has almost no effect on which videos come out. This must land before `17-feed-modes`, which exposes popular as a user-facing mode.\n\n### Context the later steps need\n\n- The mixer (`engine/server/api/recommendations/mixer.py`) takes the layer's output, optionally shuffles it (`shuffle: True` in every profile), then re-sorts each layer by the unified `score`. Only **which** candidates the layer returns matters, not their order.\n- The layer is asked for few candidates from a big pool. In `home` it is roughly batch 48 \u00d7 overfetch 1 \u00d7 gather_ratio 0.1 \u2248 5 candidates from a `DEFAULT_POPULAR_POOL_SIZE` = 5000 pool (after the author/instance caps).\n- `_max_similarity` already clamps the similarity to be at least 0 (it returns 0.0 when the best dot product is \u2264 0). Entries with no embedding or a zero-norm vector get `similarity_score` 0.0.\n- There is a precedent for this kind of draw: `_draw_page` in `engine/server/api/handlers/similar.py` does weighted sampling without replacement (Efraimidis\u2013Spirakis: key = log(u)/weight, largest keys win, zero-weight rows only fill what positive rows cannot). Whether to reuse it, share it, or write a local equivalent is a design decision for Step 2.\n\n### Functional requirements\n\n1. **Scope of the change.** Only the likes path of `PopularVideosGenerator.get_candidates` changes: the final draw after scoring (currently `_random_from_pool(ordered, limit)`). The paths with no likes, no liked/pool embeddings, or no usable liked vectors stay exactly as they are (plain `random.sample` via `_random_from_pool`). Fetching the pool, the author/instance caps, scoring, and setting `entry[\"similarity_score\"]` do not change.\n2. **Weight.** Each candidate's draw weight is `similarity_score ** alpha`, where `alpha` is the configured `weighted_random_alpha`. `similarity_score` is already \u2265 0, so this equals the issue's `max(similarity, 0.0) ** alpha`.\n3. **Weighted draw.** When `alpha > 0` and the pool (after caps) is larger than `limit`, return `limit` candidates chosen by weighted random sampling without replacement. Each candidate's chance goes up with its weight, and none is returned twice.\n4. **Zero weights.** Candidates with weight 0 are drawn only when the positive-weight candidates number fewer than `limit`. The remaining slots are filled from the zero-weight candidates uniformly at random.\n5. **All-zero fallback.** If every candidate's weight is 0, the result is a plain uniform `random.sample(pool, limit)`, the same as today.\n6. **Small pool.** When the pool has `limit` or fewer candidates, all of them are returned, the same as today.\n7. **Disabled.** When `weighted_random_alpha` is missing, `None`, 0, or negative, the likes path behaves exactly as today: a uniform `random.sample` over the scored pool.\n8. **No epsilon/diversity term.** This is a deliberate choice. The consequence is that, with likes and weighting on, popular videos with zero similarity to the likes almost never come out of the popular layer. Variety still comes from the random, fresh and explore layers.\n\n### Configuration\n\n- New per-profile key `generators.popular.weighted_random_alpha` (float) in `RECOMMENDATION_PIPELINE` in `engine/server/api/server_config.py`. It sits next to the existing `generators.popular.*` keys and is read inside the generator from its `config` dict, following the file's existing pattern (for example `float(config.get(\"weighted_random_alpha\") or 0.0)`). The issue's name `popular.weighted_random_alpha` means this key.\n- Default value **1.0** in the `home` and `upnext` profiles (operator decision). With it, the feed's behaviour changes on deploy.\n- The `guest_home` and `guest_upnext` profiles are not changed. They are only picked when there are no likes, and on that path the weighting never runs.\n- There are no environment-variable or CLI overrides.\n\n### Documentation\n\n- `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, section \"popular Layer\": list `generators.popular.weighted_random_alpha` and describe the behaviour correctly. With likes, the layer draws by weight `similarity ** alpha`; with alpha 0 or less, or all weights zero, it draws uniformly. Without likes, it takes a uniform random sample of the pool. This replaces the current inaccurate \"otherwise it is returned as-is\".\n- `engine/server/api/recommendations/docs/OVERVIEW.md`: the popular entries (layer description around line 78 and pool summary around line 109) must mention the similarity-weighted draw.\n\n### Tests\n\n- New tests in `tests/active/` that call `PopularVideosGenerator` directly with stub deps (stubbed `fetch_popular_videos`, `fetch_recent_likes`, `fetch_embeddings_by_ids`, `like_key`, and a server object with `db` and `db_lock`). They cover:\n  - with alpha > 0, higher-similarity candidates are picked clearly more often than lower-similarity ones, and no candidate is returned twice;\n  - zero-weight candidates appear only when the positive-weight candidates cannot fill `limit`;\n  - all weights zero falls back to a uniform draw that still returns `limit` distinct candidates;\n  - alpha 0 (or a missing key) behaves as today's uniform sample;\n  - a pool of `limit` or fewer returns every candidate.\n- The tests must be deterministic: seed or patch the random source, or use a trial count and bounds that cannot flake.\n\n### Baseline suite state\n\nBefore the build, the suite exited 0 (baseline variant: false). The build must leave the suite green.\n\n### Out of scope\n\n- Epsilon/diversity mixing inside the popular layer.\n- Changing the no-likes popular path, the pool query (`fetch_popular_videos`), the caps, the scoring formula, or the mixer.\n- Guest profiles, and any user-facing feed mode (that is `17-feed-modes`).\n</requirements>\n\n<conflicts>\nThe issue names the config parameter `popular.weighted_random_alpha`, but the tree keeps layer parameters per profile under `RECOMMENDATION_PIPELINE[\"profiles\"][<profile>][\"generators\"][\"popular\"]` in `engine/server/api/server_config.py`. Resolved: the key is `generators.popular.weighted_random_alpha` in each profile.\nThe issue says \"0 = disabled\", which could suggest shipping it off by default. The operator chose default 1.0 in `home` and `upnext`, so feed behaviour changes on deploy.\n`engine/server/api/recommendations/docs/LAYER_PARAMS.md` (\"popular Layer\") says that without likes the pool \"is returned as-is\", but `popular_videos.py` actually returns `random.sample(pool, limit)` on that path. Resolved: the docs will be corrected to match the code.\n`LAYER_PARAMS.md` (\"Up-next Params\") says up-next does not run the generator layers, yet the `upnext` profile carries a `generators.popular` block. The alpha default is still set there, so it takes effect wherever that profile's generators run; Step 2/3 should confirm whether that block is live.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change stays inside `engine/server/api/recommendations/candidates/popular_videos.py`, plus one config key per profile, two doc edits and one new test file.\n\nIn `get_candidates`, the three early-return paths (no likes, no liked or pool embeddings, no usable liked vectors) keep calling `_random_from_pool(pool, limit)`. The pool fetch, the author/instance caps, the scoring loop, the `entry[\"similarity_score\"]` assignment, the existing sort and the timing logs also stay as they are. Only the last line of the likes path changes. It reads `alpha` from the generator's `config` dict in the file's existing style (`float(config.get(\"weighted_random_alpha\") or 0.0)`). If `alpha` is 0 or less it calls `_random_from_pool(ordered, limit)` exactly as today. Otherwise it calls a new module-level helper next to `_random_from_pool`, something like `_weighted_from_pool(candidates, limit, alpha)`.\n\nThe helper works like this:\n\n- **Small pool.** If the pool has `limit` or fewer entries, it returns all of them, the same as `_random_from_pool` does today (requirement 6).\n- **Weights.** It computes each entry's weight as `similarity_score ** alpha` (requirement 2). The score is already clamped to at least 0, so no extra clamp is needed.\n- **Split.** It splits the pool into positive-weight entries and zero-weight entries.\n- **All zero.** If there are no positive weights, it returns `random.sample(candidates, limit)`. That is the same call as today (requirement 5).\n- **Weighted draw.** Otherwise it runs Efraimidis\u2013Spirakis over the positive entries. Each one gets `u = 1 - random.random()`, so `u` is in (0, 1], and the key `log(u) / weight`. The `limit` largest keys win. This is weighted sampling without replacement: an entry's chance of being kept rises with its weight, and none can come back twice (requirement 3).\n- **Fill.** If fewer than `limit` entries have positive weight, the gap is filled by `random.sample` over the zero-weight entries. Zero-weight entries therefore appear only when the positive ones run out, and the fill is uniform (requirement 4).\n\nThe output order does not matter because the mixer shuffles and then re-sorts by the unified score. So the helper returns the list as it comes and does no final sort.\n\nHow each requirement is met:\n\n- Requirement 1: only the final draw of the likes path is replaced.\n- Requirement 7: a missing key, `None`, 0 or a negative value all go through `or 0.0` and the `<= 0` check to the existing uniform call. A NaN also fails the `> 0` test, so it is disabled too.\n- Requirement 8: there is no epsilon term.\n\nThe randomness uses the stdlib `random` module, which the file already imports. `numpy` is not used for this, so tests can make the draw deterministic with `random.seed` or by patching `popular_videos.random`.\n\n**Configuration.** Add `\"weighted_random_alpha\": 1.0` to `generators.popular` in the `home` and `upnext` profiles in `server_config.py`, next to `pool_size` and the caps. `guest_home` and `guest_upnext` stay unchanged. I checked `resolve_profile_config_with_guest`: it picks a profile whole and does no merging, and the mixer passes `generator_configs.get(name, {})` to the generator. So the key reaches the generator only in those two profiles, and there is no inheritance to worry about.\n\n**Docs.**\n\n- `LAYER_PARAMS.md`, \"popular Layer\": list the key and replace \"otherwise it is returned as-is\". The new text says: with likes, the layer draws by weight `similarity ** alpha` without replacement, and zero-weight entries only fill a shortfall. With alpha 0 or less, or all weights zero, it draws uniformly. Without likes (or without usable embeddings), it takes a uniform random sample of the capped pool.\n- `OVERVIEW.md`: the popular layer description (around line 78) and the pool summary (around line 109) get one clause each about the similarity-weighted draw.\n\n**Tests.** A new file under `tests/active/`, set up for imports the same way as the existing active tests (the `conftest.py` sys.path setup). It builds `PopularVideosGenerator` with a `PopularVideosDeps` of stubs:\n\n- `fetch_popular_videos` returns a fixed pool.\n- `fetch_recent_likes` returns one or no like.\n- `fetch_embeddings_by_ids` returns hand-built vectors, so each entry's cosine similarity to the like is chosen exactly (0, low, high).\n- `like_key` reads an id.\n\nThe server is a `SimpleNamespace` with `db=None` and `db_lock=threading.Lock()`. The caps are set to 0 so they do not interfere.\n\nEvery test seeds `random` (or patches it) before calling. The frequency test runs a fixed number of trials under a fixed seed, with loose bounds, e.g. the high-similarity group is picked at least twice as often as the low group. With a fixed seed the result is fully reproducible, and the bounds are wide enough to survive a change of seed. The cases are exactly the five listed in the requirements. Each asserts distinct keys and `len == limit` where that applies. The zero-weight case uses fewer positive entries than `limit` and checks two things: every positive entry is present, and zero-weight entries appear only in that case.\n\n### Alternatives considered\n\n- **Import `_draw_page` from `handlers/similar.py`.** Rejected, for four reasons:\n  - It would make the recommendations package depend on a handler module, which is the wrong direction.\n  - It gets the weight from `_draw_weight(row)` (the personalized score), not from `similarity ** alpha`.\n  - It fills zero-weight rows in window order, not uniformly, which breaks requirement 4.\n  - It re-sorts its output and carries seeded-hash machinery that this layer does not need.\n- **Pull a shared weighted-sampling helper into a common module used by both.** Rejected for now. The two call sites differ in weight source, zero-fill semantics (window order vs uniform), seeding (blake2b per key vs process RNG) and output order. A shared helper would need parameters for each of those differences, which is speculative generality for two callers. It would also touch the up-next handler, which is out of scope. This is a deliberate duplication of about ten lines. If a third caller appears, both can be moved onto a helper that takes a weight function and a fill policy.\n- **`numpy.random.Generator.choice(replace=False, p=...)`.** Rejected. It raises when fewer entries have non-zero probability than the requested size, so the zero-fill would still need its own code. It also needs normalised probabilities, and it uses a different RNG from `random`, which makes the test seeding harder.\n- **`random.choices` with weights.** Rejected. It samples with replacement, so it would return duplicates or need a retry loop.\n- **Deterministic top-`limit` by similarity.** Rejected. Every request would get the same few videos, and the purpose asks for a bias, not a ranking.\n- **Softmax or temperature weighting.** Rejected. The issue specifies `similarity ** alpha`, and power weighting with the clamp already gives zero weight to unrelated videos.\n\n### Gotchas, risks, limitations\n\n- **alpha 1.0 skews only mildly.** Cosine similarities between real embeddings usually sit in a narrow positive band (roughly 0.1\u20130.6). With alpha 1, a 0.6 entry is only about 6 times as likely per slot as a 0.1 entry. Zero-weight entries will be rare in practice because the clamp only zeroes entries with non-positive similarity, missing embeddings or zero-norm vectors. The effect is real but gentle. A stronger bias means raising alpha (2\u20134), which is a config change, not a code change.\n- **Very large alpha.** Small similarities can underflow to 0.0 and are then treated as zero weight. That is consistent with requirement 4. With alpha = infinity, all weights except similarities of exactly 1 become 0. Nobody would configure that, and the code does not guard against it.\n- **`log(u)` safety.** `u = 1 - random.random()` is never 0, so `log` never fails. Weights are strictly positive in the keyed set, so there is no division by zero.\n- **Test determinism.** Seeding `random` globally inside a test affects later code only through the module-level RNG. Tests should seed per call, or patch `popular_videos.random`. Either way they must not depend on test order.\n- **Cost.** The extra work is one `log` per pool entry (at most about 5000 after caps) and one sort. That is negligible next to the existing per-entry normalisation and dot products.\n- **Existing sort kept.** The `scored.sort` in the scoring step no longer affects the output. It stays because requirement 1 freezes the scoring step, and it costs little.\n\n### Tradeoffs the operator is asked to accept\n\n- **Behaviour changes on deploy.** For every visitor with likes on `home` and `upnext`, the popular layer changes as soon as this ships, with alpha 1.0 as the default. The only switch is the config key (set it to 0 to revert). There is no env or CLI override.\n- **No epsilon term.** Popular videos with zero similarity to the likes essentially disappear from the popular layer for such visitors. Variety relies on the random, fresh and explore layers (requirement 8).\n- **Duplicated sampling logic.** About ten lines of weighted sampling are duplicated rather than shared with `similar.py`, in exchange for no cross-module coupling and no changes to the up-next handler.\n- **Tests pin exact sequences to a seed.** The deterministic tests are tied to `random`'s algorithm under a fixed seed. The assertions are properties with wide bounds, not exact sequences, so a change in Python's RNG would not break them.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"PopularVideosGenerator.get_candidates(), the final line of the likes path (line 131, `return _random_from_pool(ordered, limit)`)\">\n**What changes.** Line 131 becomes a branch. It reads `alpha = float(config.get(\"weighted_random_alpha\") or 0.0)` in the style of lines 45-47, where `config` has already been normalised to `{}` at line 44. If `alpha > 0` (written that way so a NaN is disabled too) it returns `_weighted_from_pool(ordered, limit, alpha)`. Otherwise it returns `_random_from_pool(ordered, limit)` as today. The alpha read can go at the top with the other config reads or just before the draw. Either keeps the file's style, but putting it at the top keeps all config parsing in one place.\n\n**What stays the same, verified in the file.** The three early returns at lines 72, 88 and 100 still call `_random_from_pool(pool, limit)`. Also unchanged: the pool fetch (`max(pool_size, limit)`, line 52), `apply_author_instance_caps` (56-61), the scoring loop and `entry[\"similarity_score\"] = score` (104-113), the sort (114) and the two timing logs (116-129).\n\n**What depends on it.**\n- `engine/server/api/recommendations/mixer.py:112-123` calls `generator.get_candidates(..., config=generator_configs.get(name, {}))`, drops excluded keys, then applies `random.shuffle` when `shuffle` is set. `shuffle` is True in every profile.\n- `scoring.score_candidate` (scoring.py:51,61) reads the popular entry's `similarity_score` into the unified score and writes it back, so the weighted draw also shifts the popular layer's unified scores upward.\n- The only construction site is `engine/server/api/recommendations/builder.py:156-164`.\n\n**Regression risk: low to medium.**\n- The code change is small. The behaviour change is deliberate and reaches every visitor with likes on the `home` feed.\n- A config value that is not numeric would raise in `float()`. Config is in-code dicts only, so this is not reachable from requests.\n- The early-return paths must stay byte-for-byte unchanged (requirement 1). A reviewer should diff and confirm lines 64-100 are untouched.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"new module-level helper `_weighted_from_pool(candidates, limit, alpha)`, placed next to `_random_from_pool` (lines 164-173)\">\n**What changes.** This is a new function. It should match `_random_from_pool`'s signature layout: a multi-line parameter list, `list[dict[str, Any]]` types and a one-line `\"\"\"Handle ...\"\"\"`-style docstring.\n- It opens with the same guards as `_random_from_pool`: `limit <= 0 or not candidates` returns `[]`, and `len <= limit` returns `candidates` (requirement 6, returned as-is).\n- Each weight is `float(entry.get(\"similarity_score\") or 0.0) ** alpha`.\n- Entries are split into positive-weight and zero-weight groups.\n- If no weight is positive it returns `random.sample(candidates, limit)`.\n- Otherwise it draws Efraimidis\u2013Spirakis keys, `math.log(1.0 - random.random()) / weight`, keeps the top `limit`, and fills any shortfall with `random.sample(zero, limit - len(chosen))`.\n\n**Details the implementer must get right, from the precedent `_draw_page` at `engine/server/api/handlers/similar.py:1100-1124`.**\n- **Sort key.** Sort with `key=` on the float, or carry an index tiebreak as `_draw_page` does with `(key, index, row)`. Sorting bare `(float, dict)` tuples raises `TypeError` on an exact tie, because Python then compares dicts. The existing `scored.sort` at line 114 avoids this with `key=lambda item: item[0]`, and so must the new code.\n- **`math` import.** The file currently imports `numpy as np`, `random` and `perf_counter`, but not `math`. `math.log` needs a new `import math` in the stdlib import block (lines 5-11), or use `np.log`. `math` matches `_draw_page`, and it keeps the RNG and log off numpy as the plan intends.\n- **RNG.** It must use the module-level `random` (already imported at line 10), not `np.random`, so tests can seed it or patch `popular_videos.random`.\n- **Overflow and underflow.** `similarity_score` is at most about 1.0 for normalised vectors, but float rounding can give 1.0000001. With a very large alpha that can reach `inf`, and `log(u)/inf == -0.0`, which is harmless. Small scores underflow to 0.0 and join the zero group, as the plan accepts. A negative score cannot occur, because `_max_similarity` clamps it (lines 152-161). A NaN cannot occur either: `_normalize_vector` rejects non-finite norms, but a NaN component in a vector with a finite norm could produce a NaN dot product. `best` starts at -1.0 and `nan > best` is False, so `_max_similarity` returns 0.0. The helper therefore never sees NaN from this path.\n\n**What depends on it.** Only the new branch in `get_candidates`, and the new test file.\n\n**Regression risk: low.** The function is new and isolated. The main hazards are the dict-comparison `TypeError` on tied keys and a forgotten `import math`, which would be a `NameError` at request time on the likes path only. Neither is caught unless the tests exercise the weighted branch.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"_random_from_pool() (lines 164-173) and the module import block (lines 5-13)\">\n**What changes.** `_random_from_pool` itself does not change. It is still used by the three early returns and by the alpha \u2264 0 branch. The import block gains `import math` if the helper uses `math.log`. The current order is `import logging`, dataclass, typing, a blank line, then `import numpy as np` and `import random`. Put `math` with the stdlib group, or next to `random`, following the file's loose grouping.\n\n**What depends on it.** Every return path in `get_candidates`.\n\n**Regression risk: none** if it is left untouched. A same-named `_random_from_pool` also exists in `engine/server/api/recommendations/candidates/fresh_videos.py:149`, with the identical \"sort then uniform sample\" pattern at line 135. That one is out of scope and must not be edited or imported by mistake.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"RECOMMENDATION_PIPELINE['profiles']['home']['generators']['popular'] (lines 90-98)\">\n**What changes.** Add `\"weighted_random_alpha\": 1.0,` next to `pool_size` and the caps (after line 97, `\"max_per_author\": 2,`, or after `pool_size`). A one-line comment in the style of the file's other generator comments (lines 77-79) would help, e.g. `# similarity ** alpha draw weight when likes exist (0 disables).`\n\n**What depends on it.**\n- `mixer.generate_recommendations` \u2192 `resolve_profile_config_with_guest` (`recommendations/profile.py:23-50`), then `generator_configs.get(\"popular\", {})`, then `PopularVideosGenerator.get_candidates(config=...)`.\n- The `home` profile is chosen when the visitor has likes and the mode is `home`. The mode is always `home` for the unseeded feed (`handlers/similar.py:1006-1017`).\n\n**Regression risk: low.**\n- `tests/active/test_server_config.py:117,244` does a textual `source.count('\"batch_size\": 48,') == 2`, which this edit does not affect. No test reads or validates the popular generator dict, and there is no schema validation of unknown keys.\n- `docs/project/issues/plan.md:73-76` warns that lanes 2a and 2d also edit `server_config.py`, so expect small merge conflicts in this file.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"RECOMMENDATION_PIPELINE['profiles']['upnext']['generators']['popular'] (lines 224-232)\">\n**What changes.** Add `\"weighted_random_alpha\": 1.0,` as in `home`.\n\n**Discrepancy with the plan.** The plan says the popular layer changes on deploy for visitors with likes on `home` and `upnext`. In the tree, the mixer (`generate_recommendations`) is only reached from `_handle_home` (`handlers/similar.py:737`), and `_handle_home` is only called with `mode = \"home\"` (`similar.py:1006-1009`). Seeded requests (`mode = \"upnext\"`) go to `_handle_seed_with_embedding`. That path uses `resolve_profile_config_with_guest` only for the profile name and scoring, and builds its own ANN pool with `_draw_page`. `LAYER_PARAMS.md:154` confirms: \"Up-next ... does not run the layers above. The `upnext` / `guest_upnext` profile supplies only its scoring weights\". So the key in `upnext` has no runtime effect today. Adding it keeps the profiles symmetric and is harmless, but the operator tradeoff \"behaviour changes on `home` and `upnext`\" overstates the reach. The real change is `home` only.\n\n**What depends on it.** Nothing at runtime today (grep: the only `generate_recommendations(` call is similar.py:737).\n\n**Regression risk: none.** The key is inert. Flagged so the plan and docs do not claim an up-next behaviour change.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"guest_home (lines 176-184) and guest_upnext (lines 285-293) popular generator dicts, unchanged\">\n**What changes.** Nothing. Guest profiles are selected only when `has_likes` is False (`profile.py:31-40`). The popular generator then also sees no likes and takes the early return at line 72, so the key would be dead there anyway.\n\n**Edge case.** The mixer and the generator each call `fetch_recent_likes` separately (mixer.py:69 and 88, popular_videos.py:48). If a like appears between those calls, a guest profile could reach the likes path with no key. It would then fall back to uniform, which is correct under requirement 7.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/profile.py\" element=\"resolve_profile_config_with_guest() (lines 23-50), read only\">\n**What changes.** Nothing. I verified the plan's claim: it returns `profiles[name]` whole, with no merge or inheritance. So the key reaches the generator only from the profile it is written in.\n\n**What depends on it.** `mixer.py:71` and `handlers/similar.py:773`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/mixer.py\" element=\"generate_recommendations() (lines 60-145), consumer, unchanged\">\n**What changes.** Nothing. It passes `config=generator_configs.get(name, {})` at line 117. It filters `excluded` and then `random.shuffle`s when `shuffle` is set (lines 120-123). `_soft_mix_candidates` then re-scores and re-ranks. This confirms that the helper's output order is irrelevant, so no final sort is needed.\n\n**What depends on it.** Every home feed request.\n\n**Regression risk: low.**\n- The mixer also calls the module-level `random.shuffle`. A test that patches `popular_videos.random` does not affect it, because it is a separate module attribute. A test that calls `random.seed` globally does affect it.\n- Behaviour shift: popular candidates with likes now have systematically higher `similarity_score`, so they score higher in unified scoring (`w_sim` = 1.0 in `home`). This is intended.\n</impact>\n<impact path=\"engine/server/api/recommendations/builder.py\" element=\"PopularVideosDeps construction (lines 156-164) and fetch_popular_videos_filtered (109-113)\">\n**What changes.** Nothing. `PopularVideosDeps` keeps its fields, and no new dependency is injected, because alpha comes through `config` and not through deps.\n\n**What depends on it.** The Engine's startup wiring.\n\n**Regression risk: none,** provided the dataclass fields are not changed. The new test constructs `PopularVideosDeps` directly with all five fields, including `max_likes`.\n</impact>\n<impact path=\"engine/server/api/recommendations/filters.py\" element=\"apply_author_instance_caps() (lines 31-96), used by the generator, unchanged; relevant to test design\">\n**What changes.** Nothing.\n\n**Test-design facts.**\n- `get_candidates` always passes `like_key`. So even with both caps at 0, the early return at line 47-48 does not fire, and entries are deduplicated by `like_key` (lines 74-77). The test's pool entries need distinct keys, or they collapse silently.\n- Entries without `channel_id` or `instance_domain` pass uncapped.\n\n**Regression risk: none** for production. For the test, colliding keys would quietly shrink the pool.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_draw_page() / _draw_weight() / _seeded_uniform() (lines 1088-1124), precedent only, unchanged\">\n**What changes.** Nothing. The plan deliberately duplicates about ten lines of this logic rather than importing it. The two differ in three ways: fill order (window order there, `random.sample` here), weight source (`_draw_weight` there, `similarity ** alpha` here), and RNG (`np.random.default_rng` or blake2b there, stdlib `random` here).\n\n**What depends on it.** The up-next draw.\n\n**Regression risk: none,** as long as it is not touched. `docs/project/issues/plan.md:70` lists lane 2a (issue 09) as delivered and owning `similar.py`. Do not edit it, to avoid lane conflicts.\n</impact>\n<impact path=\"tests/active/test_popular_weighted_random.py\" element=\"new test file (name indicative)\">\n**What changes.** This is a new file covering the five required cases, with stub `PopularVideosDeps` and `server = SimpleNamespace(db=None, db_lock=threading.Lock())`.\n\n**Critical correction to the plan's import setup.**\n- The plan says to set up imports \"the same way as the existing active tests (the `conftest.py` sys.path setup)\". But `tests/active/conftest.py:37-39` only puts `client/backend` on `sys.path`, not the Engine.\n- More importantly, `popular_videos.py` does `import numpy as np` at line 9. The pytest interpreter from the root `pixi.toml` has only `python` and `pytest`, with no numpy. `tests/active/test_server_config.py:73` states \"pytest's own interpreter has no numpy\", and `test_search_fusion.py:10-11` says \"`data.search` imports numpy, which only the Engine's environment has, so each check runs in a child on the Engine's interpreter\".\n- So a direct `from recommendations.candidates.popular_videos import ...` in the test process will fail with `ModuleNotFoundError: numpy`.\n- The test must follow the `test_search_fusion.py` / `test_similar.py` pattern instead:\n  - a `textwrap.dedent` child script, run with `subprocess.run([str(ENGINE_PY), \"-c\", _CHILD, str(SERVER_DIR), json.dumps(case)])`;\n  - `sys.path[:0] = [server_dir, server_dir + \"/api\"]` inside the child, because `popular_videos` imports `recommendations.filters`, which resolves from `engine/server/api`;\n  - the child reports JSON back.\n- `ENGINE_PY` can be imported from `conftest` (as `test_similar.py:109` does) or redefined as in `test_search_fusion.py:25`.\n- The stub vectors must also be built inside the child with numpy.\n\n**Other test-design gotchas found in the code.**\n- **Pool size.** `get_candidates` fetches `max(pool_size, limit)` (line 52). If the test config leaves `pool_size` at 0 and the stub honours the requested count, the pool equals `limit`, and every case takes the small-pool early return inside the helper. So either set `pool_size` above `limit`, or have the stub ignore the count.\n- **Embedding stub.** `fetch_embeddings_by_ids` is called twice under the lock, first with `likes` and then with `pool` (lines 76-77). The stub must return a dict keyed by `like_key` for whichever list it gets. If the liked video is also in the pool, it is not removed here, because like dedup happens in the mixer.\n- **Alpha in config.** Alpha must be in the `config` passed to `get_candidates` (for example `{\"weighted_random_alpha\": 1.0, \"pool_size\": N, \"max_per_author\": 0, \"max_per_instance\": 0}`). The disabled cases (missing, `None`, 0, negative) need an assertion that tells the uniform call apart from the weighted one. For example, patch `popular_videos._weighted_from_pool` or `random.random` and assert it is not called, or compare against `random.sample` under the same seed.\n- **Seeding.** Seeding happens in the child process, so it cannot leak into other tests. That fully removes the test-order concern the plan raises.\n- **Timeout.** Engine interpreter start-up costs about 1 s per subprocess. Batch the cases into one child run, or a few, as `test_similar.py` does with its `cases` JSON.\n\n**Regression risk: medium for the build.** A test written as the plan describes would error at collection or import time, not fail meaningfully.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"sys.path setup (lines 31-43) and ENGINE_PY constant (line 32)\">\n**What changes.** Nothing. The new test may import `ENGINE_PY` and `ROOT` from here. It does not provide Engine import paths. The plan's reference to \"the conftest.py sys.path setup\" is inaccurate: `test_random_videos.py:24-29` does its own `sys.path` insert of `engine/server` and `engine/server/api`, and that works only because `data.random_videos` does not need numpy.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"HOME_BATCH_SIZE_LITERAL count and config load (lines 116-117, 181-185, 231-247)\">\n**What changes.** Nothing. It loads and execs `server_config.py` and counts the literal `\"batch_size\": 48,` (expects 2). Adding `weighted_random_alpha` lines does not change that count or break exec.\n\n**Regression risk: none,** unless someone reformats the `batch_size` lines while editing nearby.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"popular pool read tests, unchanged\">\n**What changes.** Nothing. They exercise `data.random_videos.fetch_popular_videos` (the SQL ordering), which is upstream of the generator and untouched.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/fresh_videos.py\" element=\"identical sort-then-uniform-sample pattern (lines 120-135, _random_from_pool at 149), out of scope\">\n**What changes.** Nothing. I record it because it has the same \"scoring barely matters\" defect and a same-named helper. It is not part of requirement 1. Do not refactor both onto a shared helper in this build.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\" element=\"'popular Layer' section (lines 137-150)\">\n**What changes.** Add `- generators.popular.weighted_random_alpha` to the \"Layer Params\" list (after line 147), with a short gloss, for example \"draw weight exponent when likes exist; 0, negative or missing disables\".\n\nReplace the Behavior text at lines 149-150. The current text reads \"with likes, the pool is re-ranked by similarity; otherwise it is returned as-is (popularity with a soft freshness bonus)\". \"As-is\" is wrong, since the code does `random.sample`. \"Soft freshness bonus\" is also wrong: the previous build noted that neither the pool query nor the generator applies one.\n\nThe new text should say:\n- With likes, the layer draws `limit` entries without replacement, weighted by `similarity ** alpha`, and zero-weight entries only fill a shortfall.\n- With alpha \u2264 0, or when all weights are zero, it draws uniformly.\n- Without likes, or without usable embeddings, it takes a uniform random sample of the capped pool.\n- A pool of `limit` or fewer entries is returned whole.\n\n**Regression risk: none** (docs).\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/OVERVIEW.md\" element=\"\u00a73 popular bullet (lines 78-83) and \u00a74 popular pool line (line 109)\">\n**What changes.**\n- **\u00a73.** Lines 82-83 currently read \"If likes exist, it is re-ranked by similarity. / Selection: random sample from the pool after sorting.\" Rewrite them: with likes, selection is a similarity-weighted draw (`similarity ** weighted_random_alpha`, without replacement); otherwise it is a uniform random sample. The plan says \"around line 78\". The lines that actually change are 82-83.\n- **\u00a74.** Line 109, \"if likes exist, re-ranked by similarity; then caps\", is slightly out of order: in the code the caps (line 56) come before scoring. Change it to something like \"then caps; if likes exist, drawn weighted by similarity\".\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\" element=\"node H3 (line 34), `Popular pool<br/>rank by similarity if likes`\">\n**What changes.** The plan misses this. The node describes the popular selection as ranking by similarity, which was already inaccurate (the code sampled uniformly) and becomes more so. Change it to something like `Popular pool<br/>similarity-weighted draw if likes`. It is a Mermaid label, so keep `<br/>` and avoid characters that break Mermaid parsing: `**` and parentheses inside `[...]` need care.\n\n**Regression risk: none,** unless the edit breaks the Mermaid syntax.\n</impact>\n<impact path=\"docs/project/issues/16-popular-weighted-random.md\" element=\"Status line and issue lifecycle\">\n**What changes.** On delivery, per `docs/project/triage-labels.md`: set Status to `enhancement, complete` and move the issue to `docs/project/issues/archive/`. This is normally the harvest step's job. The current Status is `enhancement, needs-triage`. The issue's \"(optionally with a small epsilon)\" is resolved as no epsilon (requirement 8), and a Comments note could record that.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"Delivered list and F3-M3 line (line 58)\">\n**What changes.** On delivery, add a Delivered line for issue `16`, following the format of lines 17 and 21: with likes, the home feed's popular layer is a similarity-weighted draw, `generators.popular.weighted_random_alpha` (default 1.0, 0 disables), and the plan path. Line 58 (F3-M3) lists issue `16` as related and can keep only `17`, or mark 16 delivered. This is likely a harvest-step edit, and I list it for completeness.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"Wave 2 table, lane 2c (line 72)\">\n**What changes.** Optionally mark lane 2c as delivered, as lane 2a is (\"Delivered.\"). The files listed are accurate: `popular_videos.py` and `server_config.py`. The new test file and three docs are not listed, which does not matter for the lane-conflict purpose.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/issues/17-feed-modes.md\" element=\"'Popular: top by likes/views' (line 18), dependency on 16 (line 23)\">\n**What changes.** Nothing in this build. Issue 17 depends on 16 landing first. When 17 exposes popular as a user-facing mode, whether that mode uses the likes-weighted draw is 17's decision. I record it because 16's behaviour becomes user-visible there.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary (Interaction signal, line 7)\">\n**What changes.** Nothing is required. The glossary defines no \"popular layer\" or \"draw weight\" term. Adding one is optional and not requested.\n\n**Regression risk: none.**\n</impact>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\">\n\"popular Layer\" section (lines 137-150):\n- Add `generators.popular.weighted_random_alpha` to Layer Params.\n- Replace lines 149-150. The \"returned as-is\" and \"soft freshness bonus\" claims are both wrong. The new text: with likes, a draw without replacement weighted by `similarity ** alpha`, where zero-weight entries only fill a shortfall. With alpha \u2264 0 or missing, or when all weights are zero, a uniform draw. Without likes or usable embeddings, a uniform random sample of the capped pool. A pool of `limit` or fewer is returned whole.\n- The key has runtime effect only in the `home` profile, because the mixer never runs for `upnext` (line 154 already says so).\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/OVERVIEW.md\">\n- \u00a73 popular bullet, lines 82-83: \"re-ranked by similarity\" and \"random sample from the pool after sorting\" become a similarity-weighted draw with likes and a uniform sample otherwise.\n- \u00a74 line 109, popular pool: say the caps come first, then a draw weighted by similarity when likes exist.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\">\nLine 34: change the node label `H3[Popular pool<br/>rank by similarity if likes]` to something like `similarity-weighted draw if likes`, keeping the Mermaid syntax valid. The plan does not list this doc.\n</doc>\n<doc path=\"docs/project/issues/16-popular-weighted-random.md\">\nOn delivery, set Status to `enhancement, complete` and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`. Note that no epsilon term was chosen.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nOn delivery, add a Delivered line for issue `16` (similarity-weighted popular draw on the home feed, `generators.popular.weighted_random_alpha`, default 1.0, 0 disables) and update the F3-M3 \"Related\" list at line 58.\n</doc>\n<doc path=\"docs/project/issues/plan.md\">\nOptionally mark lane 2c (line 72) as delivered, as lane 2a is.\n</doc>\n</docs_checklist>\n\n<highest_risk>\ntests/active/test_popular_weighted_random.py (new): the plan imports `popular_videos` directly via \"the conftest.py sys.path setup\", but that module imports numpy at line 9, and the pytest interpreter has no numpy (`test_server_config.py:73`, `test_search_fusion.py:10-11`). The test has to run its cases in a child on `ENGINE_PY`. Also, `pool_size` of 0 makes the pool equal `limit`, so the weighted path would never run.\nengine/server/api/recommendations/candidates/popular_videos.py `_weighted_from_pool` (new): sorting `(key, dict)` tuples without a `key=` or an index tiebreak raises `TypeError` on a tie, and `math` is not yet imported. Either would break the likes path of every home feed at request time, and only a test that exercises the weighted branch would catch it.\nengine/server/api/server_config.py `upnext` profile: the plan's claim that behaviour changes on `upnext` is wrong. The mixer is only reached with mode `home` (`handlers/similar.py:1006-1017`), so the `upnext` key is inert. The operator tradeoff and any doc text saying up-next changes would be inaccurate.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked every inventory entry against its file. All of them hold. The plan will work as designed, and the change reaches less than the plan says. Only the home feed changes at runtime, for visitors with likes. The key added to `upnext` has no effect. The inventory already records the two real problems: the plan's test-import setup, which would fail without numpy, and the plan's claim that up-next behaviour changes. I found nothing new. The loop has converged.\n<question id=\"1\">\nYes. `popular_videos.py:130-131` is the single final draw of the likes path. The other three returns (72, 88, 100) and the whole scoring block (102-129) can stay as they are. `similarity_score` is already clamped to 0 or more by `_max_similarity` (lines 156-161). `float(config.get(...) or 0.0)` matches lines 45-47, and a NaN alpha fails `> 0`. `ordered` comes from `scored`, which is already sorted with `key=` at line 114, so the ES helper can take it directly. The precedent `_draw_page` (`similar.py:1100-1124`) shows the same algorithm running in this codebase, including the `(key, index, row)` tiebreak the new code needs. The profile path is confirmed: `profile.py:42-43` returns `profiles[mode]` whole, and `mixer.py:117` passes `generator_configs.get(name, {})`. So the key reaches the generator only in `home`, and only when `has_likes` is true.\n</question>\n<question id=\"2\">\n- **Visible change.** Home-feed popular candidates for visitors with likes lean toward videos similar to those likes. Their `similarity_score` rises on average, and `score_candidate` (scoring.py:51,61) reuses it with `w_sim` 1.0 in `home`. The popular layer therefore also ranks slightly higher in the unified mix. This is intended.\n- **Up-next.** Nothing changes. `generate_recommendations` is called only from `_handle_home` (similar.py:737). Seeded requests go to `_handle_seed_with_embedding`, which uses the profile only to get scoring weights.\n- **Guests.** Nothing changes. Guest profiles are chosen only without likes (profile.py:31-40), and the generator then takes the no-likes early return.\n- **Cost.** One `log` and one sort per pool entry. This is negligible.\n- **Tests.** The new test must run in an Engine-interpreter child process. `popular_videos.py:9` imports numpy, and pytest's interpreter has none (test_server_config.py:73, test_search_fusion.py:10-11).\n</question>\n<question id=\"3\">\n- **Import.** Add `import math`. The file has only `numpy`, `random` and `perf_counter` (lines 9-11).\n- **Sort key.** The ES sort needs a `key=` or an index tiebreak so exact ties never compare dicts.\n- **Early returns.** Leave the three early returns and `_random_from_pool` untouched.\n- **Test file.** Build it on the `test_search_fusion.py` child pattern: `ENGINE_PY` and `sys.path[:0] = [server, server/api]`. Construct the stub vectors inside the child. Give pool entries distinct `like_key`s, because `apply_author_instance_caps` dedups by `like_key` even with caps at 0 (filters.py:47,74-77). Make the pool larger than `limit` via `pool_size`, or the helper's small-pool return hides the weighted branch.\n- **Docs.** Update `LAYER_PARAMS.md:149-150`, `OVERVIEW.md:82-83` and 109, and `PIPELINE_DIAGRAM.md:34`. The last one is not in the plan's doc list, but the inventory carries it.\n- **Nothing else.** No change is needed in the mixer, builder, profile resolution, `fresh_videos.py` or `similar.py`.\n</question>\n<question id=\"4\">\n- **Before.** On the home feed with likes, the popular layer took a uniform `random.sample` of the capped pool. The similarity sort had no effect on which videos were picked.\n- **After (alpha > 0).** It draws without replacement with weight `similarity ** alpha`. Zero-similarity videos appear only when there are too few positive-weight ones to fill `limit`.\n- **Unchanged.** The layer is still uniform when there are no likes, no usable embeddings, alpha \u2264 0 or missing, or every weight is zero. A pool of `limit` or fewer is still returned whole. Pool contents, caps and output size are the same.\n- **Order.** Output order still has no effect, because the mixer shuffles (mixer.py:122-123) and then re-ranks by unified score.\n- **Not altered.** Up-next and guest feeds.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Correct the operator tradeoff wording from \"`home` and `upnext`\" to \"`home` only\". The upnext key stays in for symmetry, and the docs should not claim an up-next change (LAYER_PARAMS.md:154 already says up-next skips the layers). Cost: one sentence. Nothing in the design changes, so I have not raised this as a conflict.\n2. Tell the test-writing step to use the Engine-interpreter child pattern (`test_search_fusion.py:23-60`) instead of the \"conftest sys.path setup\". Batch all five cases into one child run. Cost: a slightly more elaborate test file, and about 1 s of interpreter start-up per child. Without this, the test fails at import with `ModuleNotFoundError: numpy` and gates nothing.\n3. Include `PIPELINE_DIAGRAM.md:34` (node H3) in the doc edits. Keep the Mermaid label free of `**` and parentheses, e.g. `Popular pool<br/>similarity-weighted draw if likes`. Cost: one line.\n4. Have the helper's tests reach the weighted branch: `pool_size` greater than `limit`, distinct keys, and at least one test with alpha > 0 where the pool is larger than `limit`. Otherwise a missing `import math` or a dict-comparison tie error would only surface in production. Cost: none beyond test design.\n5. Informational, no action: `docs/project/issues/plan.md:111` lists lane 6b (issue 29, recommendations overview doc) as depending on 16. This build's `OVERVIEW.md` edits are input to that later rewrite. Keep them short and accurate. Expect `server_config.py` merge conflicts with lanes 2a and 2d, as the inventory notes.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft: similarity-weighted draw in the popular layer (issue 16)\n\nNote on the brief: the \"ladder the draft is written against\" section came through as the literal placeholder `{rat_tail_ladder}`, so no ladder was given. This draft is checked against the plan, the eight requirements and the settled impact inventory. It converged on the second pass (see \"Check against plan and requirements\").\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/recommendations/candidates/popular_videos.py` | Adds `import math`. Adds one config read at the top of `get_candidates`. Line 131 becomes a two-way branch. Adds a new helper `_weighted_from_pool` after `_random_from_pool`. |\n| `engine/server/api/server_config.py` | Adds `\"weighted_random_alpha\": 1.0` to `home` and `upnext` \u2192 `generators.popular`. Guest profiles are untouched. |\n| `tests/active/test_popular_weighted_random.py` | New file. All cases run in one Engine-interpreter child and are seeded per trial. |\n| `engine/server/api/recommendations/docs/LAYER_PARAMS.md` | Adds the key to the list and replaces the Behavior text. |\n| `engine/server/api/recommendations/docs/OVERVIEW.md` | Rewrites \u00a73 lines 82-83 and \u00a74 line 109. |\n| `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` | Changes the H3 node label (line 34). |\n\nThe issue, roadmap and plan.md lifecycle edits belong to the harvest step, so they are not drafted here.\n\n### `popular_videos.py`\n\n**Imports (lines 5-11).** `math` goes into the stdlib group. The rest of the file's loose grouping stays as it is:\n\n```python\nimport logging\nimport math\nfrom dataclasses import dataclass\nfrom typing import Any, Callable\n```\n\n**Config read.** It goes with the other reads (after line 47), in the file's style:\n\n```python\n        max_per_author = int(config.get(\"max_per_author\") or 0)\n        weighted_random_alpha = float(config.get(\"weighted_random_alpha\") or 0.0)\n```\n\nA missing key or `None` goes through `or 0.0` and becomes 0.0. A 0 or a negative value becomes itself. A NaN stays NaN and fails the `> 0` test below. In each of those cases the draw is disabled.\n\n**The last line of the likes path (line 131)** becomes:\n\n```python\n        ordered = [item[1] for item in scored]\n        if weighted_random_alpha > 0:\n            return _weighted_from_pool(ordered, limit, weighted_random_alpha)\n        return _random_from_pool(ordered, limit)\n```\n\nLines 42-130 stay byte-for-byte the same except for the one added read line. That covers the three early returns (72, 88, 100), the fetch, the caps, the scoring, `entry[\"similarity_score\"] = score`, the sort (114) and the timing logs.\n\n**New helper**, placed directly after `_random_from_pool`, with the same signature layout:\n\n```python\ndef _weighted_from_pool(\n    candidates: list[dict[str, Any]],\n    limit: int,\n    alpha: float,\n) -> list[dict[str, Any]]:\n    \"\"\"Handle weighted from pool: draw without replacement by similarity_score ** alpha (Efraimidis-Spirakis); zero weights only fill a shortfall, uniformly.\"\"\"\n    if limit <= 0 or not candidates:\n        return []\n    if len(candidates) <= limit:\n        return candidates\n    keyed: list[tuple[float, dict[str, Any]]] = []\n    unweighted: list[dict[str, Any]] = []\n    for entry in candidates:\n        weight = float(entry.get(\"similarity_score\") or 0.0) ** alpha\n        if not weight > 0:\n            unweighted.append(entry)\n            continue\n        keyed.append((math.log(1.0 - random.random()) / weight, entry))\n    if not keyed:\n        return random.sample(candidates, limit)\n    keyed.sort(key=lambda item: item[0], reverse=True)\n    chosen = [item[1] for item in keyed[:limit]]\n    if len(chosen) < limit:\n        chosen.extend(random.sample(unweighted, limit - len(chosen)))\n    return chosen\n```\n\n**What the helper guarantees:**\n- **Output size and duplicates.** If the input has more than `limit` entries, the output has exactly `limit` entries and no entry appears twice. Each input entry sits in exactly one of `keyed` or `unweighted`, and `random.sample` draws without replacement. A shortfall means `len(keyed) < limit`, so `len(unweighted) = len(candidates) - len(keyed) > limit - len(keyed)` and the fill sample is always feasible.\n- **Small pool.** If the input has `limit` or fewer entries, all of them come back as-is, the same as `_random_from_pool` (requirement 6).\n- **All zero.** If no weight is positive, the result is exactly `random.sample(candidates, limit)`. No `random.random()` call happens before it, so the RNG stream matches today's uniform call under the same seed (requirement 5).\n- **Where zero-weight entries appear.** They appear only when `len(keyed) < limit`, and then they are drawn uniformly (requirement 4).\n- **Key safety.** `u = 1 - random.random()` is in (0, 1], so `log` never fails. The weight is strictly positive, so there is no division by zero. A weight of `inf` gives a key of `-0.0`, which is harmless.\n- **Sort.** The sort uses `key=` on the float only, so tied keys never compare dicts (the `TypeError` hazard noted in the impact inventory).\n- **NaN.** `not weight > 0` sends a NaN weight to the zero group. `_max_similarity` should already make NaN unreachable, so this costs nothing.\n- **Order.** The output is returned without a final sort. The mixer shuffles it and then re-sorts by unified score, so the order is irrelevant.\n- **RNG.** The helper uses only the module-level `random` (already imported), so a test can seed it or patch it.\n\n**Decisions:**\n- This is a local copy of the `_draw_page` idea, not an import of it. The weight source, the fill policy (uniform here, window order there), the RNG and the output order all differ.\n- The copy is a deliberate duplication of about fifteen lines. Its ceiling is two call sites. The upgrade path, when a third caller appears, is one helper that takes a weight function and a fill policy.\n- `similar.py` and `fresh_videos.py` are not touched.\n\n### `server_config.py`\n\n`home` \u2192 `generators.popular` (lines 90-98) and `upnext` \u2192 `generators.popular` (lines 224-232) get the same two lines after `\"max_per_author\": 2,`:\n\n```python\n                    \"max_per_author\": 2,\n                    # similarity ** alpha draw weight when likes exist (0 disables).\n                    \"weighted_random_alpha\": 1.0,\n                },\n```\n\n- `guest_home` and `guest_upnext` stay unchanged.\n- The `\"batch_size\": 48,` literal count checked in `test_server_config.py` is unaffected.\n\n**Flag, per the settled impact inventory.** The plan's tradeoff says behaviour changes \"on `home` and `upnext`\". In the tree, the mixer runs only for `home`, so the `upnext` key is inert today. It is added only to keep the two profiles symmetric. The docs below say the key takes effect in `home` only. The operator-facing tradeoff should read \"changes on deploy for visitors with likes on the home feed\".\n\n### `tests/active/test_popular_weighted_random.py`\n\n**Why the plan's import setup changes.** `popular_videos` imports numpy. The pytest interpreter does not have numpy, and `conftest.py` puts only `client/backend` on the path. So this file follows the `test_search_fusion.py` pattern instead: a `textwrap.dedent` child runs on `ENGINE_PY` with `sys.path[:0] = [server, server + \"/api\"]` and reports back as JSON.\n\n**One subprocess.** All cases run in one child from a module-scoped fixture. That is one Engine interpreter start-up of about 1 s.\n\n**Determinism.** Every trial reseeds `random` inside the child with a string seed (`random.seed(f\"{name}:{trial}\")`). String seeds are deterministic across processes. Nothing leaks into other tests, and test order does not matter.\n\n**Stubs:**\n- The pool is a JSON object mapping id to nominal similarity. `None` means the entry has no embedding.\n- Each vector is `[s, sqrt(1 - s\u00b2)]` against a like vector `[1, 0]`, so the cosine equals `s`. A negative `s` is clamped to 0 by `_max_similarity`.\n- `fetch_popular_videos` ignores the requested count and always returns the whole fixed pool. This avoids the trap where `max(pool_size, limit)` makes the pool equal `limit`.\n- Ids are distinct, so the `like_key` dedup inside the caps does not collapse the pool.\n- Both caps are 0.\n- The disabled cases replace `popular_videos._weighted_from_pool` with a function that raises. A wrong branch then crashes the child, and the fixture's return-code assert fails.\n- The uniform cases also recompute `random.sample(ordered_ids, limit)` under the same seed. `ordered_ids` is the pool sorted by clamped nominal similarity, descending, and the sort is stable, like the generator's `scored.sort`. The test asserts equality with that sample. This works because `random.sample` picks the same indices whatever the element type is.\n\n```python\n\"\"\"Similarity-weighted draw in the popular layer.\n\n- With likes and `weighted_random_alpha` > 0, the layer draws `limit` candidates without replacement, weighted by `similarity_score ** alpha`: closer videos come out clearly more often, none twice.\n- Zero-weight candidates only fill what the positive ones cannot; if every weight is zero the draw is today's uniform sample.\n- A missing, None, zero, negative or NaN alpha keeps today's uniform `random.sample`.\n- A pool of `limit` or fewer comes back whole.\n\n`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nimport textwrap\n\nimport pytest\n\nfrom conftest import ENGINE_PY, ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nLIMIT = 5\n\n_CHILD = textwrap.dedent(\n    \"\"\"\n    import json, math, random, sys, threading\n    from types import SimpleNamespace\n    sys.path[:0] = [sys.argv[1], sys.argv[1] + \"/api\"]\n    import numpy as np\n    from recommendations.candidates import popular_videos\n    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator\n\n    WEIGHTED = popular_videos._weighted_from_pool\n    SERVER = SimpleNamespace(db=None, db_lock=threading.Lock())\n\n    def vector(sim):\n        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)\n\n    def generator(pool):\n        table = {\"like\": np.array([1.0, 0.0], dtype=np.float32)}\n        table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})\n        return PopularVideosGenerator(PopularVideosDeps(\n            fetch_popular_videos=lambda db, count: [{\"video_id\": vid} for vid in pool],\n            fetch_recent_likes=lambda user_id, count: [{\"video_id\": \"like\"}],\n            fetch_embeddings_by_ids=lambda db, rows: {r[\"video_id\"]: table[r[\"video_id\"]] for r in rows if r[\"video_id\"] in table},\n            like_key=lambda row: row[\"video_id\"],\n            max_likes=10,\n        ))\n\n    def refuse(*args, **kwargs):\n        raise AssertionError(\"weighted draw ran while disabled\")\n\n    out = {}\n    for case in json.loads(sys.argv[2]):\n        pool, limit = case[\"pool\"], case[\"limit\"]\n        config = {\"pool_size\": len(pool), \"max_per_author\": 0, \"max_per_instance\": 0}\n        if \"alpha\" in case:\n            config[\"weighted_random_alpha\"] = float(\"nan\") if case[\"alpha\"] == \"nan\" else case[\"alpha\"]\n        popular_videos._weighted_from_pool = refuse if case.get(\"disabled\") else WEIGHTED\n        ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)\n        gen = generator(pool)\n        draws, expected = [], []\n        for trial in range(case[\"trials\"]):\n            random.seed(f\"{case['name']}:{trial}\")\n            draws.append([row[\"video_id\"] for row in gen.get_candidates(SERVER, \"user\", limit, config=config)])\n            if case.get(\"uniform\"):\n                random.seed(f\"{case['name']}:{trial}\")\n                expected.append(random.sample(ordered, limit))\n        out[case[\"name\"]] = {\"draws\": draws, \"expected\": expected}\n    popular_videos._weighted_from_pool = WEIGHTED\n    print(json.dumps(out))\n    \"\"\"\n)\n\n\ndef _pool(**groups: tuple[int, float | None]) -> dict[str, float | None]:\n    return {f\"{prefix}{i}\": sim for prefix, (count, sim) in groups.items() for i in range(count)}\n\n\nHI_LO = _pool(hi=(10, 0.9), lo=(10, 0.1))\nDISABLED = {\"disabled_missing\": {}, \"disabled_none\": {\"alpha\": None}, \"disabled_zero\": {\"alpha\": 0}, \"disabled_negative\": {\"alpha\": -1.0}, \"disabled_nan\": {\"alpha\": \"nan\"}}\n\nCASES = [\n    {\"name\": \"skew\", \"pool\": HI_LO, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 400},\n    {\"name\": \"zero_fill\", \"pool\": {**_pool(p=(3, 0.5), z=(5, 0.0)), \"neg0\": -0.5, \"none0\": None}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 100},\n    {\"name\": \"zero_unused\", \"pool\": _pool(p=(6, 0.5), z=(10, 0.0)), \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 200},\n    {\"name\": \"all_zero\", \"pool\": {**_pool(z=(10, 0.0)), \"neg0\": -0.3, \"none0\": None}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 50, \"uniform\": True},\n    *({\"name\": name, \"pool\": HI_LO, **extra, \"limit\": LIMIT, \"trials\": 50, \"uniform\": True, \"disabled\": True} for name, extra in DISABLED.items()),\n    {\"name\": \"small_equal\", \"pool\": {\"a\": 0.9, \"b\": 0.5, \"c\": 0.0, \"d\": None, \"e\": 0.2}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 3},\n    {\"name\": \"small_under\", \"pool\": {\"a\": 0.9, \"b\": 0.0, \"c\": 0.4}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 3},\n]\n\n\n@pytest.fixture(scope=\"module\")\ndef draws() -> dict[str, dict[str, list]]:\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", _CHILD, str(SERVER_DIR), json.dumps(CASES)], capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    return json.loads(run.stdout)\n\n\ndef _assert_full_and_distinct(results: list[list[str]]) -> None:\n    for draw in results:\n        assert len(draw) == LIMIT and len(set(draw)) == LIMIT, draw\n\n\ndef test_closer_candidates_are_drawn_clearly_more_often_and_never_twice(draws):\n    results = draws[\"skew\"][\"draws\"]\n    _assert_full_and_distinct(results)\n    hi = sum(vid.startswith(\"hi\") for draw in results for vid in draw)\n    lo = sum(vid.startswith(\"lo\") for draw in results for vid in draw)\n    assert hi >= 3 * lo, (hi, lo)  # expected ~9:1 per slot at alpha 1; 3:1 cannot flake under any seed\n\n\ndef test_zero_weight_candidates_only_fill_what_positive_ones_cannot(draws):\n    filled = draws[\"zero_fill\"][\"draws\"]\n    _assert_full_and_distinct(filled)\n    fill_ids: set[str] = set()\n    for draw in filled:\n        assert {\"p0\", \"p1\", \"p2\"} <= set(draw), draw  # every positive-weight candidate is taken first\n        fill_ids |= set(draw) - {\"p0\", \"p1\", \"p2\"}\n    assert fill_ids == {\"z0\", \"z1\", \"z2\", \"z3\", \"z4\", \"neg0\", \"none0\"}  # the fill spreads over every zero-weight candidate\n    unused = draws[\"zero_unused\"][\"draws\"]\n    _assert_full_and_distinct(unused)\n    assert all(vid.startswith(\"p\") for draw in unused for vid in draw)  # enough positives: zero weights never appear\n\n\ndef test_all_zero_weights_fall_back_to_the_uniform_sample(draws):\n    case = draws[\"all_zero\"]\n    _assert_full_and_distinct(case[\"draws\"])\n    assert case[\"draws\"] == case[\"expected\"]\n\n\n@pytest.mark.parametrize(\"name\", list(DISABLED))\ndef test_a_missing_none_zero_negative_or_nan_alpha_keeps_the_uniform_sample(draws, name):\n    case = draws[name]  # the child's weighted helper raised if called, so reaching here means the uniform branch ran\n    _assert_full_and_distinct(case[\"draws\"])\n    assert case[\"draws\"] == case[\"expected\"]\n\n\n@pytest.mark.parametrize(\"name\", [\"small_equal\", \"small_under\"])\ndef test_a_pool_of_limit_or_fewer_comes_back_whole(draws, name):\n    pool = next(case[\"pool\"] for case in CASES if case[\"name\"] == name)\n    for draw in draws[name][\"draws\"]:\n        assert sorted(draw) == sorted(pool)\n```\n\n**Why each assertion holds, and that none can flake:**\n- **skew.** At alpha 1 each hi entry carries 9 times the weight of a lo entry, so nearly every slot goes to hi. The 3:1 bound sits far below that, and a fixed seed makes the run reproducible anyway.\n- **zero_fill.** There are 3 positive entries for `limit` 5, so every draw takes all three plus 2 of the 7 zero-weight entries (0.0, negative clamped to 0, missing embedding). The chance that 100 trials miss one particular zero entry is about (15/21)^100 \u2248 1e-15.\n- **zero_unused.** There are 6 positive entries for `limit` 5, so the zero group is never reached.\n- **all_zero.** It asserts equality with `random.sample(ordered, 5)`, because the helper consumes no RNG before that sample. All scores are 0.0, so the generator's stable reverse sort leaves pool order unchanged, and `ordered` in the child reproduces it.\n- **Disabled.** The uniform branch is `_random_from_pool(ordered, limit)`, which is `random.sample(ordered, 5)`. The two groups have distinct scores, and within a group the dots are identical, so the stable sort order matches `ordered`.\n- **Small pool.** A pool of `limit` or fewer entries is returned whole.\n\n### Docs\n\n**`LAYER_PARAMS.md`.** Add after line 147:\n\n```markdown\n- `generators.popular.weighted_random_alpha` \u2014 draw-weight exponent when likes exist; 0, negative or missing disables (uniform draw). Set in `home` (1.0); the `upnext` value is inert because the mixer does not run for up-next.\n```\n\nReplace lines 149-150 with:\n\n```markdown\nBehavior: the pool is capped first. With likes and usable embeddings, each entry's `similarity_score` is its best cosine to the liked videos (clamped at 0), and the layer draws `limit` entries without replacement weighted by `similarity_score ** weighted_random_alpha`; zero-weight entries only fill slots the positive-weight ones cannot, uniformly at random. With alpha \u2264 0 or missing, or when every weight is zero, the draw is uniform. Without likes or usable embeddings, the layer takes a uniform random sample of the capped pool. A pool of `limit` or fewer entries is returned whole.\n```\n\n**`OVERVIEW.md` \u00a73, lines 82-83.** Replace with:\n\n```markdown\n  If likes exist, each entry gets `similarity_score` (best cosine to the likes).\n  Selection: with likes, a draw without replacement weighted by `similarity_score ** weighted_random_alpha` (zero weights only fill a shortfall); otherwise a uniform random sample from the pool.\n```\n\n**`OVERVIEW.md` \u00a74, line 109.** Replace with:\n\n```markdown\n- **popular pool**: top by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then likes and views; then caps; if likes exist, drawn weighted by similarity to the likes.\n```\n\n**`PIPELINE_DIAGRAM.md`, line 34.** Replace with the label below. It contains no parentheses or `**`, so the Mermaid syntax stays valid:\n\n```\n    G3 --> H3[Popular pool<br/>similarity-weighted draw if likes]\n```\n\n### Check against plan and requirements\n\n**Pass 1.** Two problems found and fixed:\n- The plan's test import path (`conftest` sys.path) cannot import numpy. The test was moved to an Engine-interpreter child, as the impact inventory directs.\n- The pool stub honoured `count`, which would have forced every case into the small-pool early return. The stub was changed to always return the fixed pool.\n\n**Pass 2.** Every item checks out:\n\n| Requirement | How it is met |\n|---|---|\n| R1: only the final draw changes | Only line 131 changes, plus one config read. The early returns are untouched. |\n| R2: weight is `similarity_score ** alpha` | The helper computes exactly that. |\n| R3: weighted draw without replacement, higher weight more likely | Efraimidis\u2013Spirakis with the top `limit` keys. Covered by the skew test. |\n| R4: zero weights only fill a shortfall, uniformly | Uniform `random.sample` fill. Covered by the zero_fill and zero_unused tests. |\n| R5: all-zero fallback | Exactly `random.sample(candidates, limit)`. The test asserts equality with it. |\n| R6: small pool | The guard returns the pool whole, as today. Covered by the small-pool tests. |\n| R7: disabled | Missing, `None`, 0, negative and NaN all reach `_random_from_pool` unchanged. Tested with the weighted helper patched to refuse. |\n| R8: no epsilon term | None is added. |\n| Config | The key is in `home` and `upnext`, and absent from guest profiles. |\n| Docs | All three docs edits above. |\n| Suite | The existing `test_server_config` count is unaffected. The new tests need only `ENGINE_PY`, which the existing active tests already require. |\n\n**Still open for the operator** (a tradeoff wording issue, not a defect): the plan says behaviour changes on `home` and `upnext`, but the real change is `home` only.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the public `PopularVideosGenerator.get_candidates(server, user_id, limit, config=...)`. It is driven with stub `PopularVideosDeps`: a fixed pool that ignores `count`, one like `[1, 0]`, and 2-D vectors `[s, sqrt(1-s\u00b2)]` so each cosine is exactly `s`. The caps are 0 and the server is a `SimpleNamespace(db=None, db_lock=threading.Lock())`. Harness: `tests/active/test_popular_weighted_random.py` runs every case in one Engine-interpreter child (`ENGINE_PY -c _CHILD SERVER_DIR CASES_JSON`, `sys.path[:0] = [server, server + \"/api\"]`), which reseeds `random` per trial with a string seed and reports JSON. This follows the existing ENGINE_PY child precedent in `test_search_fusion.py` and `test_internal_client_reads.py`; that route is needed because the pytest interpreter lacks numpy. Asserts for clause_1: skew (10 hi at 0.9 vs 10 lo at 0.1, alpha 1, 400 trials): every draw has `limit` distinct ids, and hi hits \u2265 3 \u00d7 lo hits. zero_fill (3 positive, 7 zero-weight including negative and missing-embedding, limit 5): all 3 positives are in every draw, and across trials the fill covers every zero-weight id. zero_unused (6 positive, 10 zero): no zero-weight id ever appears. Asserts for clause_2: all_zero and the five disabled configs (key missing, None, 0, -1.0, NaN) each equal `random.sample(ordered, limit)` recomputed under the same seed. In the disabled cases `popular_videos._weighted_from_pool` is replaced by a function that raises, so taking the wrong branch fails the fixture's return-code assert. Regression guard: pools of exactly `limit` and fewer than `limit` come back whole.</checkpoint>\n<name>Similarity-weighted popular draw</name>\n<intent>`PopularVideosGenerator.get_candidates` in `popular_videos.py` ends its likes path in a new `_weighted_from_pool` draw that favours candidates closer to the likes whenever `weighted_random_alpha` is positive (1.0 in the `home` and `upnext` profiles), and ends it in today's uniform `_random_from_pool` sample otherwise.</intent>\n<clause_1>With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`.</clause_1>\n<clause_2>With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed.</clause_2>\n<files>engine/server/api/recommendations/candidates/popular_videos.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_popular_weighted_random.py (NEW)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThere is one phase because the change is a single behaviour at a single call site. It is one branch on line 131 plus one helper of about 20 lines, and one test file drives both the weighted path and the uniform guard through the same `get_candidates` seam. Splitting the weighted draw from the disabled/uniform guard would give a phase whose checkpoint is already green before it lands, since today's code already draws uniformly. So the Intent cuts into two clauses: the weighted draw's properties, and exact equality with the uniform sample when disabled or all-zero. The small-pool case is kept in the checkpoint as a regression guard, not as a clause, because it is already true today (R6). Two items get no clause, on purpose. First, the `weighted_random_alpha: 1.0` literal in `server_config.py` is configuration data with no behaviour of its own. The settled draft's test does not read it, so the only checks are the green full suite (`test_server_config` still loads and counts the profiles) and review. The operator saw this and approved it. Second, the LAYER_PARAMS.md, OVERVIEW.md and PIPELINE_DIAGRAM.md edits are human-facing documentation, so they are not a phase; Step 9 writes them from what was delivered. Flags: the brief's {principles}, {shape_ladder-ladder} and {tdd_seams} slots arrived as unfilled placeholders, so the seam comes from the tree's existing ENGINE_PY child-process tests. As the draft notes, the mixer runs only for `home`, so the behaviour change on deploy reaches the home feed only, and the `upnext` key has no effect today. The operator was told about both.\n</rationale>",
    "author:tests/tmp/test_16_popular_weighted_random_phase1.py": "<items>\n<item id=\"D5b\">\n<disposition>fixed</disposition>\n<what>Added `\"neg0\": -0.5` and `\"none0\": None` to the `zero_unused` pool at :83, which becomes 6 at 0.5, 10 at 0.0, one negative and one with no embedding. The docstring clause now has a surplus-positive case covering every zero-weight kind it names. :126 now carries it: `[vid for draw in unused for vid in draw if not vid.startswith(\"p\")] == []` fails on any `neg0` or `none0` draw. The comment on that line now names all three kinds. A wrong implementation that weights a missing embedding as 1.0 gives none0 185 hits over the 200 trials, and one that weights a negative by `abs` gives neg0 147 hits. The correct reference draw gives 0 (seen in probe_16_zero_unused). `neg0` and `none0` do reach the scored pool, because :123 requires both in the zero_fill union. That is the positive control for this absence assertion.</what>\n</item>\n</items>\n\n<findings_addressed>\nNo CRITICAL from either auditor. Claim rec 1 (D5b uncarried): taken. neg0/none0 added to the zero_unused pool at :83, so :126 now carries it (see item D5b). Claim rec 2 (inf alpha, empty pool, limit 0): not taken. No clause in C1/C2 or the docstring names those edges, and adding them would grow the checkpoint beyond the phase's must_prove. Shape rec 1 (no cross-alpha comparison): not taken. C1 asks for a \"clearly more often\" skew, not a monotonic dependence on alpha's size, and the auditor marks it non-blocking.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:101 (via _assert_full_and_distinct at :107, :117, :125): every skew, skew_half, zero_fill and zero_unused draw has exactly 5 distinct ids. :111: hi hits >= 3\u00d7lo at alpha 1.0 and >= 2\u00d7lo at 0.5. :112: lo > 0. :121: p0\u2013p2 are in every zero_fill draw. :123: the zero_fill fill union equals all 7 zero-weight ids. :126: zero_unused (6 positives, plus 0.0, negative and missing-embedding ids) never draws a non-positive id.</assertion>\n<expected>Reference draw: 1773:227 at alpha 1.0 and 1468:532 at 0.5. zero_fill positives appear in 100/100 draws and the fill covers z0\u2013z4, neg0 and none0. zero_unused has 0 non-positive ids.</expected>\n<wrong_implementation>Today's uniform random.sample: 974:1026 and 1042:958 fail :111; a zero_fill draw missing a positive fails :121; zero_unused draws 663 non-positive ids (neg0 52, none0 54), which fails :126. Treating a missing embedding as weight 1.0 draws none0 185 times, and weighting a negative by abs draws neg0 147 times; both fail :126. A deterministic top-limit pick fails :112 (lo 0). A pool-order fill (always z0, z1) fails :123. Sampling with replacement fails :101.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:132: every all_zero draw (every weight 0 at alpha 1.0) equals random.sample(ordered, 5), recomputed under the same per-trial seed. :139, parametrized over missing/None/0/-1.0/NaN on LO_HI: each draw equals random.sample(ordered, 5) under the same seed. :101 via :131, :138 checks each draw is full and distinct.</assertion>\n<expected>Draws are identical to the seeded uniform sample over the similarity-sorted pool: equal_expected True on today's code for all_zero and all five disabled cases.</expected>\n<wrong_implementation>Several wrong implementations make the list differ within 50 trials: a weighted draw that runs while alpha is disabled (NaN slipping past a `<= 0` guard, or `sim**0 == 1` treated as weighted), extra RNG consumption, or an all-zero pool that takes the weighted/fill path. Sampling the unsorted, low-first pool also differs, because LO_HI inserts lo first.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. :126 is an absence assertion, but three things arm it. :125 requires 5 distinct ids in each of the 200 draws. :123 shows neg0 and none0 reach the scored pool in zero_fill. Today's code draws 663 non-positive ids in zero_unused. Delete the weighting and :126 goes red.\n2. No. The expected values in :132 and :139 are recomputed in the child with random.sample on the similarity order under the same seed. That is the disabled-path contract, not production's transformation. If production's weighted branch were taken instead, the lists would differ. :126 compares against a literal empty list, derived from the pool's positive/zero split.\n3. No. The skew is read at two alphas over 400 trials each. The zero-weight behaviour is read in a shortfall case and a surplus case. C2 is read across five disabled forms plus all-zero, 50 trials each.\n4. No. The only doubles are the PopularVideosDeps fetch lambdas (DB and embedding store, a severed layer) and a SimpleNamespace server. PopularVideosGenerator and the draw logic run for real.\n5. Yes, it collects. This edit changes only a dict literal and a comment. Line numbers are unchanged, and probe_16_zero_unused imports the checkpoint module and ran the edited zero_unused case in the Engine child with RC 0.\n6. Yes. The new expected value (zero_unused never draws neg0 or none0) is observed from the probe's reference draw: 0 non-positive ids. The wrong variants were observed at 185 and 147 hits, and today's code at 663.\n7. Yes, it is still red for its own reason. Today's code makes the skew tests fail at :111 and the zero-weight test fail at :121, and it would also fail at :126 (neg0 52 and none0 54 among 663 non-positive ids). The C2 and small-pool tests pass on today's uniform path, as intended. My tools cannot delete files, so tests/tmp/probe_16_zero_unused.py (and the earlier probe_16_* files) remain and should be removed. None of them match test_*.py.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_16_popular_weighted_random_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:111 \u2014 `hi >= SKEW[name][1] * lo`, run on the lo-first 10\u00d70.9 / 10\u00d70.1 pool over 400 seeded trials: at least 3:1 at alpha 1.0 (`skew`) and at least 2:1 at alpha 0.5 (`skew_half`). Line 107 (`_assert_full_and_distinct`) goes with it and checks that every draw has `limit` distinct ids. Line 112 (`lo > 0`) checks the result is a draw and not a top-`limit` cut.</assertion>\n<expected>A reference Efraimidis\u2013Spirakis draw, run in probe `tests/tmp/probe_16_reference_draw.py` under the same seeds, gave hi:lo 1773:227 at alpha 1.0 and 1468:532 at alpha 0.5. Both clear their bounds, and lo is above 0. Against the code as it stands, the run showed (974, 1026) for `skew` and (1042, 958) for `skew_half`, so both fail at line 111.</expected>\n<wrong_implementation>Today's uniform `random.sample(ordered, limit)` at line 131 reads 974:1026 and 1042:958, which is red for both. An alpha read in the file's `int(config.get(...) or 0)` style turns 0.5 into 0, so that path is uniform: `skew_half` reads about 1:1 and is red, while `skew` stays green. A deterministic top-`limit` by similarity gives lo == 0, which is red at line 112. A with-replacement `random.choices` draw repeats ids, which is red at line 101 through line 107.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:121 and :123 \u2014 in `zero_fill` (3 candidates at 0.5; 7 zero-weight candidates at 0.0, \u22120.5 or with no embedding; limit 5; 100 trials) every draw contains p0, p1 and p2. Across the trials the fill covers all 7 zero-weight ids. Line 126: in `zero_unused` (6 at 0.5, 10 at 0.0) no id without the `p` prefix ever appears. Lines 117 and 125 check `limit` distinct ids per draw.</assertion>\n<expected>Under the reference draw in the probe, every positive appears in every draw, and the union of the fills is {neg0, none0, z0..z4} (seen: `zero_fill union ['neg0', 'none0', 'p0', 'p1', 'p2', 'z0', 'z1', 'z2', 'z3', 'z4']`). Against the current code, the run failed at line 121 on the draw ['z4', 'z1', 'z3', 'z0', 'neg0'], where p0, p1 and p2 are all missing.</expected>\n<wrong_implementation>A uniform sample drops positives from draws, which is red at line 121 (the draw above) and would be red at line 126. A zero-weight fill taken in window order, as `_draw_page` does, always fills with z0 and z1, so line 123 sees {z0, z1} and is red. A weighted draw that gives zero weights a small nonzero weight sometimes lets a zero-weight id displace a positive, which is red at line 121 or line 126.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:139 \u2014 for alpha missing, None, 0, \u22121.0 and NaN on the lo-first pool, `case[\"draws\"] == case[\"expected\"]`. The expected value is `random.sample(ordered, 5)` under the same per-trial seed over 50 trials. `ordered` is the pool sorted by clamped similarity (hi first), not the pool's own lo-first order. Line 138 checks `limit` distinct ids.</assertion>\n<expected>Equal for all five, and green against the current code, as the run showed (5 of the 8 passing tests). This clause guards existing behaviour: it says the disabled path stays exactly as it is today.</expected>\n<wrong_implementation>A disabled alpha that still goes to a weighted helper uses up `random.random()` before sampling, so the draws differ from `expected`. The same happens with an alpha read that turns NaN into \"enabled\" (for example `if alpha != 0`). A disabled path that samples the unsorted `pool` instead of `ordered` also differs: the probe found 50 of 50 seeded samples differ (`ordered head ['hi0', 'hi1', 'hi2'] pool head ['lo0', 'lo1', 'lo2']`). An `int(nan)` read raises in the child and fails the fixture at line 95.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:132 \u2014 with alpha 1.0 and every weight 0 (0.0, \u22120.3, no embedding), `case[\"draws\"] == case[\"expected\"]`, the same-seed `random.sample(ordered, 5)`, over 50 trials. Line 131 checks `limit` distinct ids.</assertion>\n<expected>Equal, and green against the current code, as the run showed. It is a regression guard for the all-zero fallback.</expected>\n<wrong_implementation>A helper that calls `random.random()` for every entry before noticing that no weight is positive shifts the stream, so the draws differ from `expected`. So does one that treats zero weights as tiny positive weights and runs the keyed draw. A helper that returns `[]` or only the (empty) positive group when all weights are zero is red at line 101 through line 131.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 no, after the rewrite. The docstring's claims map onto lines 107/111/112 (distinct `limit`, skew at alpha 1.0 and 0.5, still a draw), 121/123/126 (zero weights only fill a shortfall, spread over all of them), 132 (all-zero equals the uniform sample), 139 (missing/None/0/\u22121.0/NaN equal the uniform sample from `ordered`), and 147 (small pool comes back whole). I rewrote the docstring: it no longer mentions the raising helper that I removed, and it now names alpha 0.5 and the low-first pool order.\n2. Absence only \u2014 no. Line 126 (no zero-weight id in `zero_unused`) has two controls: line 125 shows each draw returned 5 ids, and line 123 in the same test shows zero-weight ids do come through this harness when there is a shortfall. Line 121's containment and line 112 `lo > 0` are positive assertions.\n3. Echoed literal \u2014 no. `expected` is computed in the child from the nominal similarities with `random.sample`; production code is not called. Its ordering is the one C2 prescribes. Line 139 goes red if production's disabled path stops being `_random_from_pool(ordered, limit)` at popular_videos.py:131: a weighted draw, or sampling the unsorted pool. This used to be undetectable, because the old HI_LO pool was already in similarity order, so `pool` and `ordered` could not be told apart. I rewrote the pool to LO_HI (low group first). The probe showed 50/50 seeded samples differ between the two orders.\n4. One value \u2014 this was a yes, and I rewrote it. The skew was read at alpha 1.0 only. An alpha read in the file's `int(config.get(...) or 0)` style passes at 1.0 but turns 0.5 into \"disabled\". I added `skew_half` at alpha 0.5 with a 2:1 bound, set from the observed reference 1468:532 against uniform 1042:958. The disabled pool was the single-input coincidence covered in 3, now fixed.\n5. The double \u2014 this was a yes, and I rewrote it. The child replaced `popular_videos._weighted_from_pool`, a function this project owns, with one that raised. That pinned the helper's name and call structure, and it would have crashed a correct implementation whose helper falls back to `random.sample` internally. I removed `WEIGHTED`, `refusing` and `install`. The same-seed equality at line 139 already catches any weighted path, because such a path uses up `random.random()` before sampling. The only doubles left are the dependency stubs `PopularVideosDeps` takes by design (pool, likes and embedding fetchers) and a SimpleNamespace server.\n6. It collects \u2014 yes. The run shows `collected 11 items`: 2 skew + 1 zero + 1 all_zero + 5 disabled + 2 small = 11. The child imported `PopularVideosDeps` and `PopularVideosGenerator` and exited 0, since 8 tests read its JSON. The earlier `--collect-only` \"no tests\" line is the runner's summary format for that mode; the real run collected every test.\n7. Observed, not predicted \u2014 now yes. The bounds and the comment at line 110 come from runs. Probe `tests/tmp/probe_16_reference_draw.py` printed `skew weighted 1773 227 uniform 974 1026`, `skew_half weighted 1468 532 uniform 1042 958`, and the zero_fill union. The checkpoint's own run confirmed the uniform counts (974, 1026) and (1042, 958). The weighted counts come from a reference draw that follows the plan's algorithm, not from the implementation, which does not exist yet. The implementation's own counts will be confirmed when the phase runs. I removed the unobserved \"~8:1\" claim. The disabled cases passing against current code shows that the child's `ordered` matches production's `scored.sort` order for this pool.\n8. Red, not green \u2014 yes, it is red. `ValidateTests` exit status 1, `3 failed, 8 passed`: `[skew]` and `[skew_half]` at line 111, and the zero-weight test at line 121. The 8 green tests are the C2 guards and the small-pool guards. They assert that today's behaviour is kept, so they are meant to pass before and after the phase.\n9. Red for the right reason \u2014 yes. Line 111 failed with `AssertionError: (974, 1026)` / `assert 974 >= (3 * 1026)` and `(1042, 958)` / `assert 1042 >= (2 * 958)`. Line 121 failed on the draw `['z4', 'z1', 'z3', 'z0', 'neg0']` with `Extra items in the left set: 'p1' 'p2' 'p0'`. All three failures are the uniform draw at popular_videos.py:131. No control failed: the fixture's `returncode == 0` passed and the `_assert_full_and_distinct` checks on lines 107/117 passed first.\n10. Observed expected output \u2014 yes. Each row's `expected` quotes the run: (974, 1026) and (1042, 958) at line 111, the draw at line 121, and C2 green. The weighted-side values quote the probe's printed reference counts. Stray files: I have no delete tool, so the probes `tests/tmp/probe_16_reference_draw.py`, `probe_16_popular_child.py` and `probe_16_popular_harness.py` are still under tests/tmp/ and need removing. The harness probe's string replace no longer matches the rewritten child.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/api/recommendations/candidates/popular_videos.py`\n- `get_candidates` reads `weighted_random_alpha` from the per-generator config as `float(config.get(\"weighted_random_alpha\") or 0.0)`. If the value is positive, the end of the likes path now calls the new `_weighted_from_pool(scored, limit, alpha)`. If it is missing, None, 0, negative or NaN (`not alpha > 0` also catches NaN), the path does exactly what it did before: `_random_from_pool(ordered, limit)` over the pool sorted by similarity. The early returns for no likes, missing embeddings and no usable liked vectors are unchanged and still draw uniformly.\n- New `_weighted_from_pool`:\n  - Each candidate's weight is `similarity ** alpha`, or 0.0 if its clamped similarity is not positive.\n  - Candidates are split on the weight, not the score, so a tiny score that underflows to 0 under a large alpha can't cause a divide-by-zero.\n  - If no weight is positive, it hands the same similarity-ordered list to `_random_from_pool`. It uses no randomness before that, so the result is exactly the uniform sample under the same seed.\n  - A pool of `limit` or fewer comes back whole.\n  - Otherwise it runs an Efraimidis-Spirakis draw without replacement over the positive-weight candidates, keyed on `log(1 - u) / w` (the log form avoids `u ** (1/w)` underflowing to ties) and keeps the top `limit` keys.\n  - If there are fewer positive-weight candidates than `limit`, the gap is filled with `random.sample` over all zero-weight candidates.\n- Added `import math`.\n\n### `engine/server/api/server_config.py`\n- Added `\"weighted_random_alpha\": 1.0` to the `popular` generator in the `home` and `upnext` profiles, with a one-line comment on the `home` entry. `guest_home` and `guest_upnext` are unchanged; guests have no likes, so they would never reach the weighted path anyway.\n\n### `tests/active/test_popular_weighted_random.py`\n- I didn't write this file. The phase lists it as NEW, but the gating checkpoint is `tests/tmp/test_16_popular_weighted_random_phase1.py`, and I didn't touch that either. Presumably the workflow moves it into place later.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/api/recommendations/candidates/popular_videos.py: in `_weighted_from_pool`, the all-zero exit and the small-pool exit (`len(scored) <= limit`) are now one `if not positive or len(scored) <= limit:` that returns `_random_from_pool` over the similarity-ordered list. `_random_from_pool` already returns a pool of `limit` or fewer whole, so the separate list comprehension and early return are gone. The branch comment now explains why both cases go there.\n</refactors>\n\n<left_out>\nMoving the `weighted_random_alpha` read up to join the other config reads at the top of `get_candidates`, as the impacts step suggested. It is not a pure refactor: a non-numeric alpha would then raise `float()` on the no-likes and no-embedding paths too, where today it never gets read. The three copies of the timing-log-then-`_random_from_pool` early return in `get_candidates` were there before this build and this phase did not touch them, so pulling them into a helper would widen the diff past the approved scope. The odd import order (`import random` and `from time import perf_counter` sit below numpy) is also older than this build, so I left it alone. I made no change to `server_config.py`: the two added keys and the one comment on `home` are already as small as they can be. I also had no way to delete `tests/tmp/probe_16_refactor_equivalence.py` (there is no delete tool), so I emptied it. The workflow or the operator should remove it.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI checked the merge with a probe rather than the gating suite. It copied the old and new `_weighted_from_pool` side by side and ran them on 20,000 random cases (score 0, scores that underflow under alpha 200, pools smaller and larger than `limit`), each pair under the same seed. The returned lists and the RNG state afterwards were identical every time, so the refactor keeps the byte-for-byte uniform fallback the C2 checkpoint needs. The call site stays a module-global `_weighted_from_pool`, so the checkpoint's refusing patch still intercepts it. I did not run the gating test `tests/tmp/test_16_popular_weighted_random_phase1.py` myself; the workflow's run is the one that confirms it.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\" update=\"yes\">\nIn the \"popular Layer\" section, add `generators.popular.weighted_random_alpha` to the Layer Params list, glossed as the draw-weight exponent used when likes exist. It defaults to 1.0 in `home` and `upnext`, and 0, negative, NaN or a missing value disables it. Replace the Behavior sentence at lines 149-150, \"with likes, the pool is re-ranked by similarity; otherwise it is returned as-is (popularity with a soft freshness bonus)\". Every clause of it is false: the code never returned the pool as-is, and there is no freshness bonus. The new text describes the delivered state. With likes and alpha > 0, the layer draws `limit` entries without replacement, weighted by `similarity ** alpha`, and zero-weight entries only fill a shortfall, uniformly. With alpha disabled, or when every weight is zero, it takes a uniform random sample. Without likes or usable embeddings, it takes a uniform random sample of the capped pool. A pool of `limit` or fewer entries is returned whole. It should also note that the key only has an effect in `home`, because up-next does not run the layers (line 154 already says so).\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/OVERVIEW.md\" update=\"yes\">\n\u00a73, the popular bullet at lines 78-83: \"If likes exist, it is re-ranked by similarity. / Selection: random sample from the pool after sorting.\" becomes the delivered behaviour. With likes, selection is a draw without replacement weighted by `similarity ** weighted_random_alpha`. Otherwise it is a uniform random sample. \u00a74, line 109, popular pool: \"if likes exist, re-ranked by similarity; then caps\" has the order wrong and describes a ranking. Rewrite it as caps first, then a similarity-weighted draw when likes exist.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\" update=\"yes\">\nLine 34: the Mermaid node `H3[Popular pool<br/>rank by similarity if likes]` describes a ranking, but the layer does a draw. Relabel it to something like `H3[Popular pool<br/>similarity-weighted draw if likes]`, keeping `<br/>` and avoiding `**` and parentheses inside the brackets so the Mermaid still parses.\n</doc>\n<doc path=\"docs/project/issues/16-popular-weighted-random.md\" update=\"yes\">\nThe issue is delivered. Set the Status line to `enhancement, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`. Add a Comments note recording two decisions. The issue's \"optionally with a small epsilon\" is resolved as no epsilon, so with likes, popular videos with zero similarity only fill a shortfall. The key is `generators.popular.weighted_random_alpha`, set to 1.0 in `home`/`upnext`, and it only has an effect in `home`.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nAdd a Delivered line for issue `16` in the format of the existing Delivered entries. It should say that, with likes, the home feed's popular layer is a similarity-weighted draw, name `generators.popular.weighted_random_alpha` (default 1.0, 0 disables) and link the plan `docs/project/plans/20-16-popular-weighted-random.md`. In the F3-M3 \"Related\" list at line 58, drop `16` or mark it delivered, so that only `17` is outstanding.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"yes\">\nIn the Wave 2 table, lane 2c (line 72) lists issue 16 as pending, and issue 16 has now been delivered. Mark it \"Delivered.\" the same way lane 2a is marked. The files listed for the lane (`popular_videos.py`, `server_config.py`) are accurate and stay as they are.\n</doc>\n</docs>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:engine/server/api/recommendations/docs/LAYER_PARAMS.md": "<changes>\nLAYER_PARAMS.md \"popular Layer\": added `generators.popular.weighted_random_alpha` to the params list and replaced the incorrect Behavior sentence with a description of the similarity-weighted draw.\n\n- New param entry: the exponent on the draw weight when the user has likes. It is 1.0 in `home` and `upnext`. A missing, 0, negative or NaN value turns weighting off. It only affects `home`, because up-next does not run the layers.\n- The Behavior section now reads:\n  - Author and instance caps are applied first.\n  - A pool of `limit` or fewer entries is returned whole.\n  - With likes and alpha > 0, it draws without replacement, weighted by `similarity_score ** alpha`. Zero-weight entries only fill a shortfall, picked uniformly.\n  - With weighting off, or when every weight is zero, it takes a uniform sample.\n  - Without likes or usable embeddings, it takes a uniform sample.\n- One line notes there is no diversity term, so videos with zero similarity to the likes only come out to fill a shortfall.\n- Removed the old sentence (\"otherwise it is returned as-is (popularity with a soft freshness bonus)\").\n- I checked all of this against `popular_videos.py` (`get_candidates`, `_weighted_from_pool`, `_random_from_pool`, `_max_similarity`), and checked that `server_config.py` sets the key only in the `home` (line 97) and `upnext` (line 232) profiles.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/recommendations/docs/OVERVIEW.md": "<changes>\nOVERVIEW.md: the popular entries in \u00a73 and \u00a74 now describe the similarity-weighted draw, and the \u00a74 pool line applies caps before the draw.\n\n- \u00a73, popular bullet: the old \"re-ranked by similarity\" and \"random sample from the pool after sorting\" lines are replaced. With likes, each entry gets a `similarity_score` against the likes, and the layer draws without replacement, weighted by `similarity ** weighted_random_alpha`. Otherwise it takes a uniform random sample from the pool. The bullet points to `LAYER_PARAMS.md`, \"popular Layer\", for the key's default, how it is disabled, the zero-weight fill and the small-pool case, and does not repeat them here.\n- \u00a74, popular pool line: the order is now caps first, then a similarity-weighted draw if likes exist, as `get_candidates` does it (`apply_author_instance_caps` runs before scoring and `_weighted_from_pool`).\n\nI checked the text against `popular_videos.py`: the `alpha` read and the `not alpha > 0` branch, and the weight `score**alpha` in `_weighted_from_pool`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md": "<changes>\nRelabelled the popular pool node so it shows a similarity-weighted draw rather than a similarity ranking.\n\n- Line 34: `H3[Popular pool<br/>rank by similarity if likes]` \u2192 `H3[Popular pool<br/>similarity-weighted draw if likes]`. I checked the label against `popular_videos.py`: when there are likes and `weighted_random_alpha` is above 0, `get_candidates` ends in `_weighted_from_pool` (lines 131-136). The new label keeps `<br/>` and has no `**` or parentheses, so the Mermaid still parses.\n- I didn't change anything else. The alpha key, the fallback cases and the `home`-only scope belong to `LAYER_PARAMS.md` and `OVERVIEW.md`, and the diagram already points to those files.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/16-popular-weighted-random.md": "<changes>\nIssue 16 is marked `enhancement, complete` and copied to `docs/project/issues/archive/`, with a Delivered note. The original at `docs/project/issues/16-popular-weighted-random.md` still has to be deleted.\n\n- **Status.** Changed from `enhancement, needs-triage` to `enhancement, complete`, following `docs/project/triage-labels.md`.\n- **Move.** The file is now at `docs/project/issues/archive/16-popular-weighted-random.md`. I have no delete tool, so the old copy is still in the open issues directory, unchanged. It needs to be deleted to finish the move.\n- **Problem, Proposed solution and Related.** Left as the original request.\n- **New Comments entry, \"### Delivered\".** It follows the format of `archive/14-collapsible-description.md`:\n  - It links the plan `docs/project/plans/20-16-popular-weighted-random.md` with commit `<pending>`.\n  - **No epsilon:** with likes, popular videos with zero similarity only fill a shortfall. Variety comes from the random, fresh and explore layers.\n  - **Key:** the setting is `generators.popular.weighted_random_alpha`, 1.0 in `home` and `upnext`. It only has an effect in `home`, because up-next does not run the layers.\n  - **Behaviour:** the note points to the \"popular Layer\" section of `LAYER_PARAMS.md` rather than repeating the draw rules.\n- **Checked against the code.** The key is read in `popular_videos.py:131`. It is set only in the `home` and `upnext` profiles in `server_config.py` (lines 97 and 232). `_weighted_from_pool` fills a shortfall uniformly from zero-weight entries. `LAYER_PARAMS.md` line 159 says up-next does not run the layers.\n- **Other references to the old path.** `17-feed-modes.md` refers to issue 16 by its slug, so it still works after the move. The plan and record files are generated by the workflow, so I didn't edit them.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/16-popular-weighted-random.md: this is the original, unedited, and the operator or the workflow needs to delete it to finish the move into archive/ (I have no delete tool).\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nRoadmap: added a Delivered entry for issue `16` (similarity-weighted popular draw) and removed `16` from the outstanding F3-M3 and Feed ordering lines.\n\n- **Delivered**: new entry \"F3-M3, issue `16`, similarity-weighted popular draw\". When the visitor has likes, the home feed's popular layer draws candidates weighted by similarity to those likes instead of uniformly. The entry names `generators.popular.weighted_random_alpha` (1.0 by default, 0 disables it) and points to `LAYER_PARAMS.md`, \"popular Layer\", for the full behaviour rather than repeating it. It links `docs/project/plans/20-16-popular-weighted-random.md`, which exists.\n- **M3, F3-M3**: the line says issue `16` is delivered, so \"Related\" now lists only `17-feed-modes`.\n- **Implementation order**: the Feed line was `16` -> `17` and is now just `17`, because that section lists open work only. The checklist did not name this line, but leaving it would have shown a delivered issue as still pending.\n\nI checked the facts against the code. `server_config.py` sets `\"weighted_random_alpha\": 1.0` under `popular` in `home` (line 97) and `upnext` (line 232). `popular_videos.py:131` reads it as `float(config.get(\"weighted_random_alpha\") or 0.0)`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/plan.md": "<changes>\nMarked Wave 2 lane 2c (issue 16, popular weighted random) as delivered in `docs/project/issues/plan.md`.\n\n- Line 72, the Wave 2 table: the \"Depends on\" cell for lane 2c changed from `none` to `none. Delivered.`. This follows lane 2a, which writes its dependency first and then \"Delivered.\".\n- The lane's file list (`api/recommendations/candidates/popular_videos.py`, `server_config.py`) is unchanged and matches the code: `popular_videos.py` reads `weighted_random_alpha` and defines `_weighted_from_pool`, and `server_config.py` sets `\"weighted_random_alpha\": 1.0` in two profiles.\n- Nothing else in the file changed. The P3 row (`16, 17`) and wave 6's dependency on 16 still read correctly as history. I did not strike 16 in the Priorities table, since the checklist asked only for the lane marker.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_10_plan": "<harvest_file>\ndocs/project/plans/harvest-16-popular-weighted-random-plan.md\n</harvest_file>\n\n<plan>\n## Harvest plan: 16 popular weighted random\n\nThe scope is `tests/tmp/test_16_popular_weighted_random_phase1.py`. It collects 11 items from 5 test functions. It drives `engine/server/api/recommendations/candidates/popular_videos.py` through `PopularVideosGenerator.get_candidates`, running in a child process on the Engine's interpreter.\n\n**Verdicts**\n- `DURABLE`: 5\n- `REPLACES`: 0\n- `COMBINE`: 0\n- `REDUNDANT`: 0\n- `SPENT`: 0\n\n**Nothing in `tests/active` covers this generator.** No file there mentions `PopularVideosGenerator`, `popular_videos`, `weighted_random_alpha`, `_weighted_from_pool` or `_random_from_pool`. `test_random_videos.py` tests the SQL order of `data/random_videos.fetch_popular_videos`, which is a different producer.\n\n**`DURABLE`: all five tests go to the new `tests/active/test_popular_videos.py`**\n1. `test_closer_candidates_are_drawn_clearly_more_often_and_never_twice` (skew, skew_half): with a positive alpha, `limit` distinct ids come back, the 0.9 group beats the 0.1 group at least 3:1 at alpha 1.0 and 2:1 at alpha 0.5, and the 0.1 group still appears. (C1)\n2. `test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them`: zero-weight ids (0.0, negative, missing embedding) only fill a shortfall, and the fill covers all of them. (C1)\n3. `test_all_zero_weights_draw_exactly_the_uniform_sample`: when every weight is zero, the result is exactly `random.sample(ordered, limit)` under the same seed. (C2)\n4. `test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample` (missing, None, 0, -1.0, NaN): a disabled alpha gives exactly the uniform sample over the similarity-ordered pool. (C2)\n5. `test_a_pool_of_limit_or_fewer_comes_back_whole` (small_equal, small_under): regression guard that a pool of `limit` or fewer comes back whole.\n\nThe module fixtures and constants move with the tests unchanged: the `_CHILD` script, `ENGINE_PY`, `SERVER_DIR`, `LIMIT`, `_pool`, the pools, `CASES`, the `draws` fixture and `_assert_full_and_distinct`. The docstring's \"Phase 1 checkpoint\" wording is rewritten to state the rules the tests check.\n\n**Retired from `active`:** none.\n\n**`test_groups` change:** one new entry, and no existing entry changes:\n- `\"test_popular_videos.py\": [\"engine/server/api/recommendations/candidates/popular_videos.py\"]`\n- `server_config.py` is not claimed, because every case passes its own config dict. So the `weighted_random_alpha: 1.0` added to the `home` and `upnext` profiles stays untested by this harvest.\n\n**New subject file Step 5 would create:** `tests/active/test_popular_videos.py`. It is a new group and gets the new map entry above. The phase plan called the file `tests/active/test_popular_weighted_random.py`; harvest names it after the production script instead.\n\n**Things to know before approving**\n- **Probe scripts left in `tests/tmp`:** six `probe_16_*.py` files (`popular_child`, `popular_harness`, `popular_margin`, `refactor_equivalence`, `reference_draw`, `zero_unused`). They are outside the scope I was given, so Step 7 moves only the test file to `delete_me/` and `tests/tmp` will not end up empty. Say if you want them moved too.\n- **Mutation caveat:** all five tests share one module-scoped `draws` fixture that checks the child process's return code. Any mutation that crashes the child would fail all five tests at once, which proves nothing about the named test. So each Step 6 mutation has to change only the draw and keep the child running.\n- **Checkpoint description is wrong on one point:** it says the disabled cases replace `_weighted_from_pool` with a stub that raises. The file doesn't do that; it only compares the draws with the seeded uniform sample. It moves as written.\n\n**Done so far:** `tests/last_test_validation.json.preharvest` is taken and `cmp`-identical to the record. Nothing has moved, and neither the group map nor any production file has been touched.\n</plan>",
    "step_10": "<moved>\ntests/tmp/test_16_popular_weighted_random_phase1.py::test_closer_candidates_are_drawn_clearly_more_often_and_never_twice (skew, skew_half) -> tests/active/test_popular_videos.py, new group test_popular_videos.py\ntests/tmp/test_16_popular_weighted_random_phase1.py::test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them -> tests/active/test_popular_videos.py, new group test_popular_videos.py\ntests/tmp/test_16_popular_weighted_random_phase1.py::test_all_zero_weights_draw_exactly_the_uniform_sample -> tests/active/test_popular_videos.py, new group test_popular_videos.py\ntests/tmp/test_16_popular_weighted_random_phase1.py::test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample (missing, None, 0, -1.0, NaN) -> tests/active/test_popular_videos.py, new group test_popular_videos.py\ntests/tmp/test_16_popular_weighted_random_phase1.py::test_a_pool_of_limit_or_fewer_comes_back_whole (small_equal, small_under) -> tests/active/test_popular_videos.py, new group test_popular_videos.py\nThe module fixtures and constants moved unchanged: _CHILD, ROOT, SERVER_DIR, ENGINE_PY, LIMIT, _pool, the pools, CASES, the draws fixture and _assert_full_and_distinct. Only the docstring's first line changed: \"Phase 1 checkpoint: ...\" became the rule it gates.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nAdded \"test_popular_videos.py\": [\"engine/server/api/recommendations/candidates/popular_videos.py\"] to test_groups in .un/skills/devsecops/config.json, as the last key. No existing entry changed, and server_config.py is not claimed. The sandbox (confine_un_dir) blocked my edit to .un/, so the operator made this exact edit at my request, and I verified it by reading config.json. --audit-map exits 0, with no MISSING finding for test_popular_videos.py. It does show BARREN for test_popular_videos.py, as it does for 13 other groups that already existed.\n</group_map>\n\n<mutations>\ntest_closer_candidates_are_drawn_clearly_more_often_and_never_twice: in _weighted_from_pool the key `math.log(1.0 - random.random()) / weight` became `/ 1.0` (uniform over positives). RED on both params at line 111 `assert hi >= SKEW[name][1] * lo`, with (958, 1042) at alpha 1.0 and (1008, 992) at 0.5. Restored from .bak1, diff clean, GREEN 2 passed.\ntest_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them: the shortfall fill `random.sample(zero, limit - len(picked))` became `zero[: limit - len(picked)]` (pool order). RED at line 123 `assert fill_ids == set(ZERO_FILL) - positives`, where the fill was only {z0, z1} and neg0, none0, z2, z3, z4 were missing. Restored from .bak2, diff clean, GREEN 1 passed.\ntest_all_zero_weights_draw_exactly_the_uniform_sample: the no-positive fallback sampled `reversed(scored)` instead of the similarity order. RED at line 132 `assert case[\"draws\"] == case[\"expected\"]`, where the draws differed at index 0. Restored from .bak3, diff clean, GREEN 1 passed.\ntest_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample: in the disabled branch, `ordered = [item[1] for item in scored]` became `ordered = list(pool)` (pool order, not similarity order). RED on all 5 params at line 139 `assert case[\"draws\"] == case[\"expected\"]`. Restored from .bak4, diff clean, GREEN 5 passed.\ntest_a_pool_of_limit_or_fewer_comes_back_whole: in _random_from_pool, the small-pool `return candidates` became `return candidates[1:]`. RED on both params at line 147 `assert sorted(draw) == sorted(SMALL[name])`: small_equal drew ['b','c','d','e'] and small_under drew ['b','c']. Restored from .bak5, diff clean, GREEN 2 passed.\nEvery mutation left the child running: no draws-fixture returncode failure, and only the named test went red. popular_videos.py ends cmp-identical to its pre-mutation copy, and no .bak remains under engine/ or client/.\n</mutations>\n\n<cleared>\ndelete_me/ holds 6 files:\n- test_16_popular_weighted_random_phase1.py, which is the whole scope moved out of tests/tmp.\n- popular_videos.py.bak1 to .bak5, the Step 6 restore copies. Each is byte-identical to the current production file.\ntests/tmp holds none of the files in scope. It is not empty: the six probe_16_*.py files (popular_child, popular_harness, popular_margin, refactor_equivalence, reference_draw, zero_unused) were outside the scope I was given and stay there, as the plan said. Nothing was deleted; you decide what happens to delete_me/.\nClosing run: I restored the preharvest snapshot over tests/last_test_validation.json, then ran --compare. It selected 2 of 28 groups, with 26 unchanged and carried from the record:\n- test_popular_videos.py (no record): 11 passed.\n- test_search_fusion.py (no map entry; this harvest did not touch it): 10 passed.\nIn total 21 passed, 0 failed. Delta against the pre-harvest record: 11 appeared, all tests.active.test_popular_videos items; 0 departed; no new red; nothing went from red to green. That matches the harvest: 5 tests (11 items) added, 0 retired.\n</cleared>"
  },
  "requirements": "### Purpose\n\nWhen a visitor has likes, the popular layer of the recommendation feed should favour popular videos that are similar to what the visitor liked. Today `PopularVideosGenerator.get_candidates` (`engine/server/api/recommendations/candidates/popular_videos.py`) scores every pool entry by its maximum cosine similarity to the liked vectors and sorts by it. It then calls `_random_from_pool`, which does `random.sample` over the whole pool, so the similarity scoring has almost no effect on which videos come out. This must land before `17-feed-modes`, which exposes popular as a user-facing mode.\n\n### Context the later steps need\n\n- The mixer (`engine/server/api/recommendations/mixer.py`) takes the layer's output, optionally shuffles it (`shuffle: True` in every profile), then re-sorts each layer by the unified `score`. Only **which** candidates the layer returns matters, not their order.\n- The layer is asked for few candidates from a big pool. In `home` it is roughly batch 48 \u00d7 overfetch 1 \u00d7 gather_ratio 0.1 \u2248 5 candidates from a `DEFAULT_POPULAR_POOL_SIZE` = 5000 pool (after the author/instance caps).\n- `_max_similarity` already clamps the similarity to be at least 0 (it returns 0.0 when the best dot product is \u2264 0). Entries with no embedding or a zero-norm vector get `similarity_score` 0.0.\n- There is a precedent for this kind of draw: `_draw_page` in `engine/server/api/handlers/similar.py` does weighted sampling without replacement (Efraimidis\u2013Spirakis: key = log(u)/weight, largest keys win, zero-weight rows only fill what positive rows cannot). Whether to reuse it, share it, or write a local equivalent is a design decision for Step 2.\n\n### Functional requirements\n\n1. **Scope of the change.** Only the likes path of `PopularVideosGenerator.get_candidates` changes: the final draw after scoring (currently `_random_from_pool(ordered, limit)`). The paths with no likes, no liked/pool embeddings, or no usable liked vectors stay exactly as they are (plain `random.sample` via `_random_from_pool`). Fetching the pool, the author/instance caps, scoring, and setting `entry[\"similarity_score\"]` do not change.\n2. **Weight.** Each candidate's draw weight is `similarity_score ** alpha`, where `alpha` is the configured `weighted_random_alpha`. `similarity_score` is already \u2265 0, so this equals the issue's `max(similarity, 0.0) ** alpha`.\n3. **Weighted draw.** When `alpha > 0` and the pool (after caps) is larger than `limit`, return `limit` candidates chosen by weighted random sampling without replacement. Each candidate's chance goes up with its weight, and none is returned twice.\n4. **Zero weights.** Candidates with weight 0 are drawn only when the positive-weight candidates number fewer than `limit`. The remaining slots are filled from the zero-weight candidates uniformly at random.\n5. **All-zero fallback.** If every candidate's weight is 0, the result is a plain uniform `random.sample(pool, limit)`, the same as today.\n6. **Small pool.** When the pool has `limit` or fewer candidates, all of them are returned, the same as today.\n7. **Disabled.** When `weighted_random_alpha` is missing, `None`, 0, or negative, the likes path behaves exactly as today: a uniform `random.sample` over the scored pool.\n8. **No epsilon/diversity term.** This is a deliberate choice. The consequence is that, with likes and weighting on, popular videos with zero similarity to the likes almost never come out of the popular layer. Variety still comes from the random, fresh and explore layers.\n\n### Configuration\n\n- New per-profile key `generators.popular.weighted_random_alpha` (float) in `RECOMMENDATION_PIPELINE` in `engine/server/api/server_config.py`. It sits next to the existing `generators.popular.*` keys and is read inside the generator from its `config` dict, following the file's existing pattern (for example `float(config.get(\"weighted_random_alpha\") or 0.0)`). The issue's name `popular.weighted_random_alpha` means this key.\n- Default value **1.0** in the `home` and `upnext` profiles (operator decision). With it, the feed's behaviour changes on deploy.\n- The `guest_home` and `guest_upnext` profiles are not changed. They are only picked when there are no likes, and on that path the weighting never runs.\n- There are no environment-variable or CLI overrides.\n\n### Documentation\n\n- `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, section \"popular Layer\": list `generators.popular.weighted_random_alpha` and describe the behaviour correctly. With likes, the layer draws by weight `similarity ** alpha`; with alpha 0 or less, or all weights zero, it draws uniformly. Without likes, it takes a uniform random sample of the pool. This replaces the current inaccurate \"otherwise it is returned as-is\".\n- `engine/server/api/recommendations/docs/OVERVIEW.md`: the popular entries (layer description around line 78 and pool summary around line 109) must mention the similarity-weighted draw.\n\n### Tests\n\n- New tests in `tests/active/` that call `PopularVideosGenerator` directly with stub deps (stubbed `fetch_popular_videos`, `fetch_recent_likes`, `fetch_embeddings_by_ids`, `like_key`, and a server object with `db` and `db_lock`). They cover:\n  - with alpha > 0, higher-similarity candidates are picked clearly more often than lower-similarity ones, and no candidate is returned twice;\n  - zero-weight candidates appear only when the positive-weight candidates cannot fill `limit`;\n  - all weights zero falls back to a uniform draw that still returns `limit` distinct candidates;\n  - alpha 0 (or a missing key) behaves as today's uniform sample;\n  - a pool of `limit` or fewer returns every candidate.\n- The tests must be deterministic: seed or patch the random source, or use a trial count and bounds that cannot flake.\n\n### Baseline suite state\n\nBefore the build, the suite exited 0 (baseline variant: false). The build must leave the suite green.\n\n### Out of scope\n\n- Epsilon/diversity mixing inside the popular layer.\n- Changing the no-likes popular path, the pool query (`fetch_popular_videos`), the caps, the scoring formula, or the mixer.\n- Guest profiles, and any user-facing feed mode (that is `17-feed-modes`).",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe change stays inside `engine/server/api/recommendations/candidates/popular_videos.py`, plus one config key per profile, two doc edits and one new test file.\n\nIn `get_candidates`, the three early-return paths (no likes, no liked or pool embeddings, no usable liked vectors) keep calling `_random_from_pool(pool, limit)`. The pool fetch, the author/instance caps, the scoring loop, the `entry[\"similarity_score\"]` assignment, the existing sort and the timing logs also stay as they are. Only the last line of the likes path changes. It reads `alpha` from the generator's `config` dict in the file's existing style (`float(config.get(\"weighted_random_alpha\") or 0.0)`). If `alpha` is 0 or less it calls `_random_from_pool(ordered, limit)` exactly as today. Otherwise it calls a new module-level helper next to `_random_from_pool`, something like `_weighted_from_pool(candidates, limit, alpha)`.\n\nThe helper works like this:\n\n- **Small pool.** If the pool has `limit` or fewer entries, it returns all of them, the same as `_random_from_pool` does today (requirement 6).\n- **Weights.** It computes each entry's weight as `similarity_score ** alpha` (requirement 2). The score is already clamped to at least 0, so no extra clamp is needed.\n- **Split.** It splits the pool into positive-weight entries and zero-weight entries.\n- **All zero.** If there are no positive weights, it returns `random.sample(candidates, limit)`. That is the same call as today (requirement 5).\n- **Weighted draw.** Otherwise it runs Efraimidis\u2013Spirakis over the positive entries. Each one gets `u = 1 - random.random()`, so `u` is in (0, 1], and the key `log(u) / weight`. The `limit` largest keys win. This is weighted sampling without replacement: an entry's chance of being kept rises with its weight, and none can come back twice (requirement 3).\n- **Fill.** If fewer than `limit` entries have positive weight, the gap is filled by `random.sample` over the zero-weight entries. Zero-weight entries therefore appear only when the positive ones run out, and the fill is uniform (requirement 4).\n\nThe output order does not matter because the mixer shuffles and then re-sorts by the unified score. So the helper returns the list as it comes and does no final sort.\n\nHow each requirement is met:\n\n- Requirement 1: only the final draw of the likes path is replaced.\n- Requirement 7: a missing key, `None`, 0 or a negative value all go through `or 0.0` and the `<= 0` check to the existing uniform call. A NaN also fails the `> 0` test, so it is disabled too.\n- Requirement 8: there is no epsilon term.\n\nThe randomness uses the stdlib `random` module, which the file already imports. `numpy` is not used for this, so tests can make the draw deterministic with `random.seed` or by patching `popular_videos.random`.\n\n**Configuration.** Add `\"weighted_random_alpha\": 1.0` to `generators.popular` in the `home` and `upnext` profiles in `server_config.py`, next to `pool_size` and the caps. `guest_home` and `guest_upnext` stay unchanged. I checked `resolve_profile_config_with_guest`: it picks a profile whole and does no merging, and the mixer passes `generator_configs.get(name, {})` to the generator. So the key reaches the generator only in those two profiles, and there is no inheritance to worry about.\n\n**Docs.**\n\n- `LAYER_PARAMS.md`, \"popular Layer\": list the key and replace \"otherwise it is returned as-is\". The new text says: with likes, the layer draws by weight `similarity ** alpha` without replacement, and zero-weight entries only fill a shortfall. With alpha 0 or less, or all weights zero, it draws uniformly. Without likes (or without usable embeddings), it takes a uniform random sample of the capped pool.\n- `OVERVIEW.md`: the popular layer description (around line 78) and the pool summary (around line 109) get one clause each about the similarity-weighted draw.\n\n**Tests.** A new file under `tests/active/`, set up for imports the same way as the existing active tests (the `conftest.py` sys.path setup). It builds `PopularVideosGenerator` with a `PopularVideosDeps` of stubs:\n\n- `fetch_popular_videos` returns a fixed pool.\n- `fetch_recent_likes` returns one or no like.\n- `fetch_embeddings_by_ids` returns hand-built vectors, so each entry's cosine similarity to the like is chosen exactly (0, low, high).\n- `like_key` reads an id.\n\nThe server is a `SimpleNamespace` with `db=None` and `db_lock=threading.Lock()`. The caps are set to 0 so they do not interfere.\n\nEvery test seeds `random` (or patches it) before calling. The frequency test runs a fixed number of trials under a fixed seed, with loose bounds, e.g. the high-similarity group is picked at least twice as often as the low group. With a fixed seed the result is fully reproducible, and the bounds are wide enough to survive a change of seed. The cases are exactly the five listed in the requirements. Each asserts distinct keys and `len == limit` where that applies. The zero-weight case uses fewer positive entries than `limit` and checks two things: every positive entry is present, and zero-weight entries appear only in that case.\n\n### Alternatives considered\n\n- **Import `_draw_page` from `handlers/similar.py`.** Rejected, for four reasons:\n  - It would make the recommendations package depend on a handler module, which is the wrong direction.\n  - It gets the weight from `_draw_weight(row)` (the personalized score), not from `similarity ** alpha`.\n  - It fills zero-weight rows in window order, not uniformly, which breaks requirement 4.\n  - It re-sorts its output and carries seeded-hash machinery that this layer does not need.\n- **Pull a shared weighted-sampling helper into a common module used by both.** Rejected for now. The two call sites differ in weight source, zero-fill semantics (window order vs uniform), seeding (blake2b per key vs process RNG) and output order. A shared helper would need parameters for each of those differences, which is speculative generality for two callers. It would also touch the up-next handler, which is out of scope. This is a deliberate duplication of about ten lines. If a third caller appears, both can be moved onto a helper that takes a weight function and a fill policy.\n- **`numpy.random.Generator.choice(replace=False, p=...)`.** Rejected. It raises when fewer entries have non-zero probability than the requested size, so the zero-fill would still need its own code. It also needs normalised probabilities, and it uses a different RNG from `random`, which makes the test seeding harder.\n- **`random.choices` with weights.** Rejected. It samples with replacement, so it would return duplicates or need a retry loop.\n- **Deterministic top-`limit` by similarity.** Rejected. Every request would get the same few videos, and the purpose asks for a bias, not a ranking.\n- **Softmax or temperature weighting.** Rejected. The issue specifies `similarity ** alpha`, and power weighting with the clamp already gives zero weight to unrelated videos.\n\n### Gotchas, risks, limitations\n\n- **alpha 1.0 skews only mildly.** Cosine similarities between real embeddings usually sit in a narrow positive band (roughly 0.1\u20130.6). With alpha 1, a 0.6 entry is only about 6 times as likely per slot as a 0.1 entry. Zero-weight entries will be rare in practice because the clamp only zeroes entries with non-positive similarity, missing embeddings or zero-norm vectors. The effect is real but gentle. A stronger bias means raising alpha (2\u20134), which is a config change, not a code change.\n- **Very large alpha.** Small similarities can underflow to 0.0 and are then treated as zero weight. That is consistent with requirement 4. With alpha = infinity, all weights except similarities of exactly 1 become 0. Nobody would configure that, and the code does not guard against it.\n- **`log(u)` safety.** `u = 1 - random.random()` is never 0, so `log` never fails. Weights are strictly positive in the keyed set, so there is no division by zero.\n- **Test determinism.** Seeding `random` globally inside a test affects later code only through the module-level RNG. Tests should seed per call, or patch `popular_videos.random`. Either way they must not depend on test order.\n- **Cost.** The extra work is one `log` per pool entry (at most about 5000 after caps) and one sort. That is negligible next to the existing per-entry normalisation and dot products.\n- **Existing sort kept.** The `scored.sort` in the scoring step no longer affects the output. It stays because requirement 1 freezes the scoring step, and it costs little.\n\n### Tradeoffs the operator is asked to accept\n\n- **Behaviour changes on deploy.** For every visitor with likes on `home` and `upnext`, the popular layer changes as soon as this ships, with alpha 1.0 as the default. The only switch is the config key (set it to 0 to revert). There is no env or CLI override.\n- **No epsilon term.** Popular videos with zero similarity to the likes essentially disappear from the popular layer for such visitors. Variety relies on the random, fresh and explore layers (requirement 8).\n- **Duplicated sampling logic.** About ten lines of weighted sampling are duplicated rather than shared with `similar.py`, in exchange for no cross-module coupling and no changes to the up-next handler.\n- **Tests pin exact sequences to a seed.** The deterministic tests are tied to `random`'s algorithm under a fixed seed. The assertions are properties with wide bounds, not exact sequences, so a change in Python's RNG would not break them.",
  "conflicts": "none",
  "impacts": "\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"PopularVideosGenerator.get_candidates(), the final line of the likes path (line 131, `return _random_from_pool(ordered, limit)`)\">\n**What changes.** Line 131 becomes a branch. It reads `alpha = float(config.get(\"weighted_random_alpha\") or 0.0)` in the style of lines 45-47, where `config` has already been normalised to `{}` at line 44. If `alpha > 0` (written that way so a NaN is disabled too) it returns `_weighted_from_pool(ordered, limit, alpha)`. Otherwise it returns `_random_from_pool(ordered, limit)` as today. The alpha read can go at the top with the other config reads or just before the draw. Either keeps the file's style, but putting it at the top keeps all config parsing in one place.\n\n**What stays the same, verified in the file.** The three early returns at lines 72, 88 and 100 still call `_random_from_pool(pool, limit)`. Also unchanged: the pool fetch (`max(pool_size, limit)`, line 52), `apply_author_instance_caps` (56-61), the scoring loop and `entry[\"similarity_score\"] = score` (104-113), the sort (114) and the two timing logs (116-129).\n\n**What depends on it.**\n- `engine/server/api/recommendations/mixer.py:112-123` calls `generator.get_candidates(..., config=generator_configs.get(name, {}))`, drops excluded keys, then applies `random.shuffle` when `shuffle` is set. `shuffle` is True in every profile.\n- `scoring.score_candidate` (scoring.py:51,61) reads the popular entry's `similarity_score` into the unified score and writes it back, so the weighted draw also shifts the popular layer's unified scores upward.\n- The only construction site is `engine/server/api/recommendations/builder.py:156-164`.\n\n**Regression risk: low to medium.**\n- The code change is small. The behaviour change is deliberate and reaches every visitor with likes on the `home` feed.\n- A config value that is not numeric would raise in `float()`. Config is in-code dicts only, so this is not reachable from requests.\n- The early-return paths must stay byte-for-byte unchanged (requirement 1). A reviewer should diff and confirm lines 64-100 are untouched.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"new module-level helper `_weighted_from_pool(candidates, limit, alpha)`, placed next to `_random_from_pool` (lines 164-173)\">\n**What changes.** This is a new function. It should match `_random_from_pool`'s signature layout: a multi-line parameter list, `list[dict[str, Any]]` types and a one-line `\"\"\"Handle ...\"\"\"`-style docstring.\n- It opens with the same guards as `_random_from_pool`: `limit <= 0 or not candidates` returns `[]`, and `len <= limit` returns `candidates` (requirement 6, returned as-is).\n- Each weight is `float(entry.get(\"similarity_score\") or 0.0) ** alpha`.\n- Entries are split into positive-weight and zero-weight groups.\n- If no weight is positive it returns `random.sample(candidates, limit)`.\n- Otherwise it draws Efraimidis\u2013Spirakis keys, `math.log(1.0 - random.random()) / weight`, keeps the top `limit`, and fills any shortfall with `random.sample(zero, limit - len(chosen))`.\n\n**Details the implementer must get right, from the precedent `_draw_page` at `engine/server/api/handlers/similar.py:1100-1124`.**\n- **Sort key.** Sort with `key=` on the float, or carry an index tiebreak as `_draw_page` does with `(key, index, row)`. Sorting bare `(float, dict)` tuples raises `TypeError` on an exact tie, because Python then compares dicts. The existing `scored.sort` at line 114 avoids this with `key=lambda item: item[0]`, and so must the new code.\n- **`math` import.** The file currently imports `numpy as np`, `random` and `perf_counter`, but not `math`. `math.log` needs a new `import math` in the stdlib import block (lines 5-11), or use `np.log`. `math` matches `_draw_page`, and it keeps the RNG and log off numpy as the plan intends.\n- **RNG.** It must use the module-level `random` (already imported at line 10), not `np.random`, so tests can seed it or patch `popular_videos.random`.\n- **Overflow and underflow.** `similarity_score` is at most about 1.0 for normalised vectors, but float rounding can give 1.0000001. With a very large alpha that can reach `inf`, and `log(u)/inf == -0.0`, which is harmless. Small scores underflow to 0.0 and join the zero group, as the plan accepts. A negative score cannot occur, because `_max_similarity` clamps it (lines 152-161). A NaN cannot occur either: `_normalize_vector` rejects non-finite norms, but a NaN component in a vector with a finite norm could produce a NaN dot product. `best` starts at -1.0 and `nan > best` is False, so `_max_similarity` returns 0.0. The helper therefore never sees NaN from this path.\n\n**What depends on it.** Only the new branch in `get_candidates`, and the new test file.\n\n**Regression risk: low.** The function is new and isolated. The main hazards are the dict-comparison `TypeError` on tied keys and a forgotten `import math`, which would be a `NameError` at request time on the likes path only. Neither is caught unless the tests exercise the weighted branch.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"_random_from_pool() (lines 164-173) and the module import block (lines 5-13)\">\n**What changes.** `_random_from_pool` itself does not change. It is still used by the three early returns and by the alpha \u2264 0 branch. The import block gains `import math` if the helper uses `math.log`. The current order is `import logging`, dataclass, typing, a blank line, then `import numpy as np` and `import random`. Put `math` with the stdlib group, or next to `random`, following the file's loose grouping.\n\n**What depends on it.** Every return path in `get_candidates`.\n\n**Regression risk: none** if it is left untouched. A same-named `_random_from_pool` also exists in `engine/server/api/recommendations/candidates/fresh_videos.py:149`, with the identical \"sort then uniform sample\" pattern at line 135. That one is out of scope and must not be edited or imported by mistake.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"RECOMMENDATION_PIPELINE['profiles']['home']['generators']['popular'] (lines 90-98)\">\n**What changes.** Add `\"weighted_random_alpha\": 1.0,` next to `pool_size` and the caps (after line 97, `\"max_per_author\": 2,`, or after `pool_size`). A one-line comment in the style of the file's other generator comments (lines 77-79) would help, e.g. `# similarity ** alpha draw weight when likes exist (0 disables).`\n\n**What depends on it.**\n- `mixer.generate_recommendations` \u2192 `resolve_profile_config_with_guest` (`recommendations/profile.py:23-50`), then `generator_configs.get(\"popular\", {})`, then `PopularVideosGenerator.get_candidates(config=...)`.\n- The `home` profile is chosen when the visitor has likes and the mode is `home`. The mode is always `home` for the unseeded feed (`handlers/similar.py:1006-1017`).\n\n**Regression risk: low.**\n- `tests/active/test_server_config.py:117,244` does a textual `source.count('\"batch_size\": 48,') == 2`, which this edit does not affect. No test reads or validates the popular generator dict, and there is no schema validation of unknown keys.\n- `docs/project/issues/plan.md:73-76` warns that lanes 2a and 2d also edit `server_config.py`, so expect small merge conflicts in this file.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"RECOMMENDATION_PIPELINE['profiles']['upnext']['generators']['popular'] (lines 224-232)\">\n**What changes.** Add `\"weighted_random_alpha\": 1.0,` as in `home`.\n\n**Discrepancy with the plan.** The plan says the popular layer changes on deploy for visitors with likes on `home` and `upnext`. In the tree, the mixer (`generate_recommendations`) is only reached from `_handle_home` (`handlers/similar.py:737`), and `_handle_home` is only called with `mode = \"home\"` (`similar.py:1006-1009`). Seeded requests (`mode = \"upnext\"`) go to `_handle_seed_with_embedding`. That path uses `resolve_profile_config_with_guest` only for the profile name and scoring, and builds its own ANN pool with `_draw_page`. `LAYER_PARAMS.md:154` confirms: \"Up-next ... does not run the layers above. The `upnext` / `guest_upnext` profile supplies only its scoring weights\". So the key in `upnext` has no runtime effect today. Adding it keeps the profiles symmetric and is harmless, but the operator tradeoff \"behaviour changes on `home` and `upnext`\" overstates the reach. The real change is `home` only.\n\n**What depends on it.** Nothing at runtime today (grep: the only `generate_recommendations(` call is similar.py:737).\n\n**Regression risk: none.** The key is inert. Flagged so the plan and docs do not claim an up-next behaviour change.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"guest_home (lines 176-184) and guest_upnext (lines 285-293) popular generator dicts, unchanged\">\n**What changes.** Nothing. Guest profiles are selected only when `has_likes` is False (`profile.py:31-40`). The popular generator then also sees no likes and takes the early return at line 72, so the key would be dead there anyway.\n\n**Edge case.** The mixer and the generator each call `fetch_recent_likes` separately (mixer.py:69 and 88, popular_videos.py:48). If a like appears between those calls, a guest profile could reach the likes path with no key. It would then fall back to uniform, which is correct under requirement 7.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/profile.py\" element=\"resolve_profile_config_with_guest() (lines 23-50), read only\">\n**What changes.** Nothing. I verified the plan's claim: it returns `profiles[name]` whole, with no merge or inheritance. So the key reaches the generator only from the profile it is written in.\n\n**What depends on it.** `mixer.py:71` and `handlers/similar.py:773`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/mixer.py\" element=\"generate_recommendations() (lines 60-145), consumer, unchanged\">\n**What changes.** Nothing. It passes `config=generator_configs.get(name, {})` at line 117. It filters `excluded` and then `random.shuffle`s when `shuffle` is set (lines 120-123). `_soft_mix_candidates` then re-scores and re-ranks. This confirms that the helper's output order is irrelevant, so no final sort is needed.\n\n**What depends on it.** Every home feed request.\n\n**Regression risk: low.**\n- The mixer also calls the module-level `random.shuffle`. A test that patches `popular_videos.random` does not affect it, because it is a separate module attribute. A test that calls `random.seed` globally does affect it.\n- Behaviour shift: popular candidates with likes now have systematically higher `similarity_score`, so they score higher in unified scoring (`w_sim` = 1.0 in `home`). This is intended.\n</impact>\n<impact path=\"engine/server/api/recommendations/builder.py\" element=\"PopularVideosDeps construction (lines 156-164) and fetch_popular_videos_filtered (109-113)\">\n**What changes.** Nothing. `PopularVideosDeps` keeps its fields, and no new dependency is injected, because alpha comes through `config` and not through deps.\n\n**What depends on it.** The Engine's startup wiring.\n\n**Regression risk: none,** provided the dataclass fields are not changed. The new test constructs `PopularVideosDeps` directly with all five fields, including `max_likes`.\n</impact>\n<impact path=\"engine/server/api/recommendations/filters.py\" element=\"apply_author_instance_caps() (lines 31-96), used by the generator, unchanged; relevant to test design\">\n**What changes.** Nothing.\n\n**Test-design facts.**\n- `get_candidates` always passes `like_key`. So even with both caps at 0, the early return at line 47-48 does not fire, and entries are deduplicated by `like_key` (lines 74-77). The test's pool entries need distinct keys, or they collapse silently.\n- Entries without `channel_id` or `instance_domain` pass uncapped.\n\n**Regression risk: none** for production. For the test, colliding keys would quietly shrink the pool.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_draw_page() / _draw_weight() / _seeded_uniform() (lines 1088-1124), precedent only, unchanged\">\n**What changes.** Nothing. The plan deliberately duplicates about ten lines of this logic rather than importing it. The two differ in three ways: fill order (window order there, `random.sample` here), weight source (`_draw_weight` there, `similarity ** alpha` here), and RNG (`np.random.default_rng` or blake2b there, stdlib `random` here).\n\n**What depends on it.** The up-next draw.\n\n**Regression risk: none,** as long as it is not touched. `docs/project/issues/plan.md:70` lists lane 2a (issue 09) as delivered and owning `similar.py`. Do not edit it, to avoid lane conflicts.\n</impact>\n<impact path=\"tests/active/test_popular_weighted_random.py\" element=\"new test file (name indicative)\">\n**What changes.** This is a new file covering the five required cases, with stub `PopularVideosDeps` and `server = SimpleNamespace(db=None, db_lock=threading.Lock())`.\n\n**Critical correction to the plan's import setup.**\n- The plan says to set up imports \"the same way as the existing active tests (the `conftest.py` sys.path setup)\". But `tests/active/conftest.py:37-39` only puts `client/backend` on `sys.path`, not the Engine.\n- More importantly, `popular_videos.py` does `import numpy as np` at line 9. The pytest interpreter from the root `pixi.toml` has only `python` and `pytest`, with no numpy. `tests/active/test_server_config.py:73` states \"pytest's own interpreter has no numpy\", and `test_search_fusion.py:10-11` says \"`data.search` imports numpy, which only the Engine's environment has, so each check runs in a child on the Engine's interpreter\".\n- So a direct `from recommendations.candidates.popular_videos import ...` in the test process will fail with `ModuleNotFoundError: numpy`.\n- The test must follow the `test_search_fusion.py` / `test_similar.py` pattern instead:\n  - a `textwrap.dedent` child script, run with `subprocess.run([str(ENGINE_PY), \"-c\", _CHILD, str(SERVER_DIR), json.dumps(case)])`;\n  - `sys.path[:0] = [server_dir, server_dir + \"/api\"]` inside the child, because `popular_videos` imports `recommendations.filters`, which resolves from `engine/server/api`;\n  - the child reports JSON back.\n- `ENGINE_PY` can be imported from `conftest` (as `test_similar.py:109` does) or redefined as in `test_search_fusion.py:25`.\n- The stub vectors must also be built inside the child with numpy.\n\n**Other test-design gotchas found in the code.**\n- **Pool size.** `get_candidates` fetches `max(pool_size, limit)` (line 52). If the test config leaves `pool_size` at 0 and the stub honours the requested count, the pool equals `limit`, and every case takes the small-pool early return inside the helper. So either set `pool_size` above `limit`, or have the stub ignore the count.\n- **Embedding stub.** `fetch_embeddings_by_ids` is called twice under the lock, first with `likes` and then with `pool` (lines 76-77). The stub must return a dict keyed by `like_key` for whichever list it gets. If the liked video is also in the pool, it is not removed here, because like dedup happens in the mixer.\n- **Alpha in config.** Alpha must be in the `config` passed to `get_candidates` (for example `{\"weighted_random_alpha\": 1.0, \"pool_size\": N, \"max_per_author\": 0, \"max_per_instance\": 0}`). The disabled cases (missing, `None`, 0, negative) need an assertion that tells the uniform call apart from the weighted one. For example, patch `popular_videos._weighted_from_pool` or `random.random` and assert it is not called, or compare against `random.sample` under the same seed.\n- **Seeding.** Seeding happens in the child process, so it cannot leak into other tests. That fully removes the test-order concern the plan raises.\n- **Timeout.** Engine interpreter start-up costs about 1 s per subprocess. Batch the cases into one child run, or a few, as `test_similar.py` does with its `cases` JSON.\n\n**Regression risk: medium for the build.** A test written as the plan describes would error at collection or import time, not fail meaningfully.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"sys.path setup (lines 31-43) and ENGINE_PY constant (line 32)\">\n**What changes.** Nothing. The new test may import `ENGINE_PY` and `ROOT` from here. It does not provide Engine import paths. The plan's reference to \"the conftest.py sys.path setup\" is inaccurate: `test_random_videos.py:24-29` does its own `sys.path` insert of `engine/server` and `engine/server/api`, and that works only because `data.random_videos` does not need numpy.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"HOME_BATCH_SIZE_LITERAL count and config load (lines 116-117, 181-185, 231-247)\">\n**What changes.** Nothing. It loads and execs `server_config.py` and counts the literal `\"batch_size\": 48,` (expects 2). Adding `weighted_random_alpha` lines does not change that count or break exec.\n\n**Regression risk: none,** unless someone reformats the `batch_size` lines while editing nearby.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"popular pool read tests, unchanged\">\n**What changes.** Nothing. They exercise `data.random_videos.fetch_popular_videos` (the SQL ordering), which is upstream of the generator and untouched.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/fresh_videos.py\" element=\"identical sort-then-uniform-sample pattern (lines 120-135, _random_from_pool at 149), out of scope\">\n**What changes.** Nothing. I record it because it has the same \"scoring barely matters\" defect and a same-named helper. It is not part of requirement 1. Do not refactor both onto a shared helper in this build.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\" element=\"'popular Layer' section (lines 137-150)\">\n**What changes.** Add `- generators.popular.weighted_random_alpha` to the \"Layer Params\" list (after line 147), with a short gloss, for example \"draw weight exponent when likes exist; 0, negative or missing disables\".\n\nReplace the Behavior text at lines 149-150. The current text reads \"with likes, the pool is re-ranked by similarity; otherwise it is returned as-is (popularity with a soft freshness bonus)\". \"As-is\" is wrong, since the code does `random.sample`. \"Soft freshness bonus\" is also wrong: the previous build noted that neither the pool query nor the generator applies one.\n\nThe new text should say:\n- With likes, the layer draws `limit` entries without replacement, weighted by `similarity ** alpha`, and zero-weight entries only fill a shortfall.\n- With alpha \u2264 0, or when all weights are zero, it draws uniformly.\n- Without likes, or without usable embeddings, it takes a uniform random sample of the capped pool.\n- A pool of `limit` or fewer entries is returned whole.\n\n**Regression risk: none** (docs).\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/OVERVIEW.md\" element=\"\u00a73 popular bullet (lines 78-83) and \u00a74 popular pool line (line 109)\">\n**What changes.**\n- **\u00a73.** Lines 82-83 currently read \"If likes exist, it is re-ranked by similarity. / Selection: random sample from the pool after sorting.\" Rewrite them: with likes, selection is a similarity-weighted draw (`similarity ** weighted_random_alpha`, without replacement); otherwise it is a uniform random sample. The plan says \"around line 78\". The lines that actually change are 82-83.\n- **\u00a74.** Line 109, \"if likes exist, re-ranked by similarity; then caps\", is slightly out of order: in the code the caps (line 56) come before scoring. Change it to something like \"then caps; if likes exist, drawn weighted by similarity\".\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\" element=\"node H3 (line 34), `Popular pool<br/>rank by similarity if likes`\">\n**What changes.** The plan misses this. The node describes the popular selection as ranking by similarity, which was already inaccurate (the code sampled uniformly) and becomes more so. Change it to something like `Popular pool<br/>similarity-weighted draw if likes`. It is a Mermaid label, so keep `<br/>` and avoid characters that break Mermaid parsing: `**` and parentheses inside `[...]` need care.\n\n**Regression risk: none,** unless the edit breaks the Mermaid syntax.\n</impact>\n<impact path=\"docs/project/issues/16-popular-weighted-random.md\" element=\"Status line and issue lifecycle\">\n**What changes.** On delivery, per `docs/project/triage-labels.md`: set Status to `enhancement, complete` and move the issue to `docs/project/issues/archive/`. This is normally the harvest step's job. The current Status is `enhancement, needs-triage`. The issue's \"(optionally with a small epsilon)\" is resolved as no epsilon (requirement 8), and a Comments note could record that.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"Delivered list and F3-M3 line (line 58)\">\n**What changes.** On delivery, add a Delivered line for issue `16`, following the format of lines 17 and 21: with likes, the home feed's popular layer is a similarity-weighted draw, `generators.popular.weighted_random_alpha` (default 1.0, 0 disables), and the plan path. Line 58 (F3-M3) lists issue `16` as related and can keep only `17`, or mark 16 delivered. This is likely a harvest-step edit, and I list it for completeness.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"Wave 2 table, lane 2c (line 72)\">\n**What changes.** Optionally mark lane 2c as delivered, as lane 2a is (\"Delivered.\"). The files listed are accurate: `popular_videos.py` and `server_config.py`. The new test file and three docs are not listed, which does not matter for the lane-conflict purpose.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/issues/17-feed-modes.md\" element=\"'Popular: top by likes/views' (line 18), dependency on 16 (line 23)\">\n**What changes.** Nothing in this build. Issue 17 depends on 16 landing first. When 17 exposes popular as a user-facing mode, whether that mode uses the likes-weighted draw is 17's decision. I record it because 16's behaviour becomes user-visible there.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary (Interaction signal, line 7)\">\n**What changes.** Nothing is required. The glossary defines no \"popular layer\" or \"draw weight\" term. Adding one is optional and not requested.\n\n**Regression risk: none.**\n</impact>\n",
  "docs_checklist": "- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md \"popular Layer\": added `generators.popular.weighted_random_alpha` to the params list and replaced the incorrect Behavior sentence with a description of the similarity-weighted draw.\n- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular entries in \u00a73 and \u00a74 now describe the similarity-weighted draw, and the \u00a74 pool line applies caps before the draw.\n- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Relabelled the popular pool node so it shows a similarity-weighted draw rather than a similarity ranking.\n- [x] `docs/project/issues/16-popular-weighted-random.md` - updated: Issue 16 is marked `enhancement, complete` and copied to `docs/project/issues/archive/`, with a Delivered note. The original at `docs/project/issues/16-popular-weighted-random.md` still has to be deleted.\n- [x] `docs/project/roadmap.md` - updated: Roadmap: added a Delivered entry for issue `16` (similarity-weighted popular draw) and removed `16` from the outstanding F3-M3 and Feed ordering lines.\n- [x] `docs/project/issues/plan.md` - updated: Marked Wave 2 lane 2c (issue 16, popular weighted random) as delivered in `docs/project/issues/plan.md`.",
  "docs": [
    {
      "path": "engine/server/api/recommendations/docs/LAYER_PARAMS.md",
      "note": "\"popular Layer\" section (lines 137-150):\n- Add `generators.popular.weighted_random_alpha` to Layer Params.\n- Replace lines 149-150. The \"returned as-is\" and \"soft freshness bonus\" claims are both wrong. The new text: with likes, a draw without replacement weighted by `similarity ** alpha`, where zero-weight entries only fill a shortfall. With alpha \u2264 0 or missing, or when all weights are zero, a uniform draw. Without likes or usable embeddings, a uniform random sample of the capped pool. A pool of `limit` or fewer is returned whole.\n- The key has runtime effect only in the `home` profile, because the mixer never runs for `upnext` (line 154 already says so)."
    },
    {
      "path": "engine/server/api/recommendations/docs/OVERVIEW.md",
      "note": "- \u00a73 popular bullet, lines 82-83: \"re-ranked by similarity\" and \"random sample from the pool after sorting\" become a similarity-weighted draw with likes and a uniform sample otherwise.\n- \u00a74 line 109, popular pool: say the caps come first, then a draw weighted by similarity when likes exist."
    },
    {
      "path": "engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md",
      "note": "Line 34: change the node label `H3[Popular pool<br/>rank by similarity if likes]` to something like `similarity-weighted draw if likes`, keeping the Mermaid syntax valid. The plan does not list this doc."
    },
    {
      "path": "docs/project/issues/16-popular-weighted-random.md",
      "note": "On delivery, set Status to `enhancement, complete` and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`. Note that no epsilon term was chosen."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "On delivery, add a Delivered line for issue `16` (similarity-weighted popular draw on the home feed, `generators.popular.weighted_random_alpha`, default 1.0, 0 disables) and update the F3-M3 \"Related\" list at line 58."
    },
    {
      "path": "docs/project/issues/plan.md",
      "note": "Optionally mark lane 2c (line 72) as delivered, as lane 2a is."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft: similarity-weighted draw in the popular layer (issue 16)\n\nNote on the brief: the \"ladder the draft is written against\" section came through as the literal placeholder `{rat_tail_ladder}`, so no ladder was given. This draft is checked against the plan, the eight requirements and the settled impact inventory. It converged on the second pass (see \"Check against plan and requirements\").\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/recommendations/candidates/popular_videos.py` | Adds `import math`. Adds one config read at the top of `get_candidates`. Line 131 becomes a two-way branch. Adds a new helper `_weighted_from_pool` after `_random_from_pool`. |\n| `engine/server/api/server_config.py` | Adds `\"weighted_random_alpha\": 1.0` to `home` and `upnext` \u2192 `generators.popular`. Guest profiles are untouched. |\n| `tests/active/test_popular_weighted_random.py` | New file. All cases run in one Engine-interpreter child and are seeded per trial. |\n| `engine/server/api/recommendations/docs/LAYER_PARAMS.md` | Adds the key to the list and replaces the Behavior text. |\n| `engine/server/api/recommendations/docs/OVERVIEW.md` | Rewrites \u00a73 lines 82-83 and \u00a74 line 109. |\n| `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` | Changes the H3 node label (line 34). |\n\nThe issue, roadmap and plan.md lifecycle edits belong to the harvest step, so they are not drafted here.\n\n### `popular_videos.py`\n\n**Imports (lines 5-11).** `math` goes into the stdlib group. The rest of the file's loose grouping stays as it is:\n\n```python\nimport logging\nimport math\nfrom dataclasses import dataclass\nfrom typing import Any, Callable\n```\n\n**Config read.** It goes with the other reads (after line 47), in the file's style:\n\n```python\n        max_per_author = int(config.get(\"max_per_author\") or 0)\n        weighted_random_alpha = float(config.get(\"weighted_random_alpha\") or 0.0)\n```\n\nA missing key or `None` goes through `or 0.0` and becomes 0.0. A 0 or a negative value becomes itself. A NaN stays NaN and fails the `> 0` test below. In each of those cases the draw is disabled.\n\n**The last line of the likes path (line 131)** becomes:\n\n```python\n        ordered = [item[1] for item in scored]\n        if weighted_random_alpha > 0:\n            return _weighted_from_pool(ordered, limit, weighted_random_alpha)\n        return _random_from_pool(ordered, limit)\n```\n\nLines 42-130 stay byte-for-byte the same except for the one added read line. That covers the three early returns (72, 88, 100), the fetch, the caps, the scoring, `entry[\"similarity_score\"] = score`, the sort (114) and the timing logs.\n\n**New helper**, placed directly after `_random_from_pool`, with the same signature layout:\n\n```python\ndef _weighted_from_pool(\n    candidates: list[dict[str, Any]],\n    limit: int,\n    alpha: float,\n) -> list[dict[str, Any]]:\n    \"\"\"Handle weighted from pool: draw without replacement by similarity_score ** alpha (Efraimidis-Spirakis); zero weights only fill a shortfall, uniformly.\"\"\"\n    if limit <= 0 or not candidates:\n        return []\n    if len(candidates) <= limit:\n        return candidates\n    keyed: list[tuple[float, dict[str, Any]]] = []\n    unweighted: list[dict[str, Any]] = []\n    for entry in candidates:\n        weight = float(entry.get(\"similarity_score\") or 0.0) ** alpha\n        if not weight > 0:\n            unweighted.append(entry)\n            continue\n        keyed.append((math.log(1.0 - random.random()) / weight, entry))\n    if not keyed:\n        return random.sample(candidates, limit)\n    keyed.sort(key=lambda item: item[0], reverse=True)\n    chosen = [item[1] for item in keyed[:limit]]\n    if len(chosen) < limit:\n        chosen.extend(random.sample(unweighted, limit - len(chosen)))\n    return chosen\n```\n\n**What the helper guarantees:**\n- **Output size and duplicates.** If the input has more than `limit` entries, the output has exactly `limit` entries and no entry appears twice. Each input entry sits in exactly one of `keyed` or `unweighted`, and `random.sample` draws without replacement. A shortfall means `len(keyed) < limit`, so `len(unweighted) = len(candidates) - len(keyed) > limit - len(keyed)` and the fill sample is always feasible.\n- **Small pool.** If the input has `limit` or fewer entries, all of them come back as-is, the same as `_random_from_pool` (requirement 6).\n- **All zero.** If no weight is positive, the result is exactly `random.sample(candidates, limit)`. No `random.random()` call happens before it, so the RNG stream matches today's uniform call under the same seed (requirement 5).\n- **Where zero-weight entries appear.** They appear only when `len(keyed) < limit`, and then they are drawn uniformly (requirement 4).\n- **Key safety.** `u = 1 - random.random()` is in (0, 1], so `log` never fails. The weight is strictly positive, so there is no division by zero. A weight of `inf` gives a key of `-0.0`, which is harmless.\n- **Sort.** The sort uses `key=` on the float only, so tied keys never compare dicts (the `TypeError` hazard noted in the impact inventory).\n- **NaN.** `not weight > 0` sends a NaN weight to the zero group. `_max_similarity` should already make NaN unreachable, so this costs nothing.\n- **Order.** The output is returned without a final sort. The mixer shuffles it and then re-sorts by unified score, so the order is irrelevant.\n- **RNG.** The helper uses only the module-level `random` (already imported), so a test can seed it or patch it.\n\n**Decisions:**\n- This is a local copy of the `_draw_page` idea, not an import of it. The weight source, the fill policy (uniform here, window order there), the RNG and the output order all differ.\n- The copy is a deliberate duplication of about fifteen lines. Its ceiling is two call sites. The upgrade path, when a third caller appears, is one helper that takes a weight function and a fill policy.\n- `similar.py` and `fresh_videos.py` are not touched.\n\n### `server_config.py`\n\n`home` \u2192 `generators.popular` (lines 90-98) and `upnext` \u2192 `generators.popular` (lines 224-232) get the same two lines after `\"max_per_author\": 2,`:\n\n```python\n                    \"max_per_author\": 2,\n                    # similarity ** alpha draw weight when likes exist (0 disables).\n                    \"weighted_random_alpha\": 1.0,\n                },\n```\n\n- `guest_home` and `guest_upnext` stay unchanged.\n- The `\"batch_size\": 48,` literal count checked in `test_server_config.py` is unaffected.\n\n**Flag, per the settled impact inventory.** The plan's tradeoff says behaviour changes \"on `home` and `upnext`\". In the tree, the mixer runs only for `home`, so the `upnext` key is inert today. It is added only to keep the two profiles symmetric. The docs below say the key takes effect in `home` only. The operator-facing tradeoff should read \"changes on deploy for visitors with likes on the home feed\".\n\n### `tests/active/test_popular_weighted_random.py`\n\n**Why the plan's import setup changes.** `popular_videos` imports numpy. The pytest interpreter does not have numpy, and `conftest.py` puts only `client/backend` on the path. So this file follows the `test_search_fusion.py` pattern instead: a `textwrap.dedent` child runs on `ENGINE_PY` with `sys.path[:0] = [server, server + \"/api\"]` and reports back as JSON.\n\n**One subprocess.** All cases run in one child from a module-scoped fixture. That is one Engine interpreter start-up of about 1 s.\n\n**Determinism.** Every trial reseeds `random` inside the child with a string seed (`random.seed(f\"{name}:{trial}\")`). String seeds are deterministic across processes. Nothing leaks into other tests, and test order does not matter.\n\n**Stubs:**\n- The pool is a JSON object mapping id to nominal similarity. `None` means the entry has no embedding.\n- Each vector is `[s, sqrt(1 - s\u00b2)]` against a like vector `[1, 0]`, so the cosine equals `s`. A negative `s` is clamped to 0 by `_max_similarity`.\n- `fetch_popular_videos` ignores the requested count and always returns the whole fixed pool. This avoids the trap where `max(pool_size, limit)` makes the pool equal `limit`.\n- Ids are distinct, so the `like_key` dedup inside the caps does not collapse the pool.\n- Both caps are 0.\n- The disabled cases replace `popular_videos._weighted_from_pool` with a function that raises. A wrong branch then crashes the child, and the fixture's return-code assert fails.\n- The uniform cases also recompute `random.sample(ordered_ids, limit)` under the same seed. `ordered_ids` is the pool sorted by clamped nominal similarity, descending, and the sort is stable, like the generator's `scored.sort`. The test asserts equality with that sample. This works because `random.sample` picks the same indices whatever the element type is.\n\n```python\n\"\"\"Similarity-weighted draw in the popular layer.\n\n- With likes and `weighted_random_alpha` > 0, the layer draws `limit` candidates without replacement, weighted by `similarity_score ** alpha`: closer videos come out clearly more often, none twice.\n- Zero-weight candidates only fill what the positive ones cannot; if every weight is zero the draw is today's uniform sample.\n- A missing, None, zero, negative or NaN alpha keeps today's uniform `random.sample`.\n- A pool of `limit` or fewer comes back whole.\n\n`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nimport textwrap\n\nimport pytest\n\nfrom conftest import ENGINE_PY, ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nLIMIT = 5\n\n_CHILD = textwrap.dedent(\n    \"\"\"\n    import json, math, random, sys, threading\n    from types import SimpleNamespace\n    sys.path[:0] = [sys.argv[1], sys.argv[1] + \"/api\"]\n    import numpy as np\n    from recommendations.candidates import popular_videos\n    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator\n\n    WEIGHTED = popular_videos._weighted_from_pool\n    SERVER = SimpleNamespace(db=None, db_lock=threading.Lock())\n\n    def vector(sim):\n        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)\n\n    def generator(pool):\n        table = {\"like\": np.array([1.0, 0.0], dtype=np.float32)}\n        table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})\n        return PopularVideosGenerator(PopularVideosDeps(\n            fetch_popular_videos=lambda db, count: [{\"video_id\": vid} for vid in pool],\n            fetch_recent_likes=lambda user_id, count: [{\"video_id\": \"like\"}],\n            fetch_embeddings_by_ids=lambda db, rows: {r[\"video_id\"]: table[r[\"video_id\"]] for r in rows if r[\"video_id\"] in table},\n            like_key=lambda row: row[\"video_id\"],\n            max_likes=10,\n        ))\n\n    def refuse(*args, **kwargs):\n        raise AssertionError(\"weighted draw ran while disabled\")\n\n    out = {}\n    for case in json.loads(sys.argv[2]):\n        pool, limit = case[\"pool\"], case[\"limit\"]\n        config = {\"pool_size\": len(pool), \"max_per_author\": 0, \"max_per_instance\": 0}\n        if \"alpha\" in case:\n            config[\"weighted_random_alpha\"] = float(\"nan\") if case[\"alpha\"] == \"nan\" else case[\"alpha\"]\n        popular_videos._weighted_from_pool = refuse if case.get(\"disabled\") else WEIGHTED\n        ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)\n        gen = generator(pool)\n        draws, expected = [], []\n        for trial in range(case[\"trials\"]):\n            random.seed(f\"{case['name']}:{trial}\")\n            draws.append([row[\"video_id\"] for row in gen.get_candidates(SERVER, \"user\", limit, config=config)])\n            if case.get(\"uniform\"):\n                random.seed(f\"{case['name']}:{trial}\")\n                expected.append(random.sample(ordered, limit))\n        out[case[\"name\"]] = {\"draws\": draws, \"expected\": expected}\n    popular_videos._weighted_from_pool = WEIGHTED\n    print(json.dumps(out))\n    \"\"\"\n)\n\n\ndef _pool(**groups: tuple[int, float | None]) -> dict[str, float | None]:\n    return {f\"{prefix}{i}\": sim for prefix, (count, sim) in groups.items() for i in range(count)}\n\n\nHI_LO = _pool(hi=(10, 0.9), lo=(10, 0.1))\nDISABLED = {\"disabled_missing\": {}, \"disabled_none\": {\"alpha\": None}, \"disabled_zero\": {\"alpha\": 0}, \"disabled_negative\": {\"alpha\": -1.0}, \"disabled_nan\": {\"alpha\": \"nan\"}}\n\nCASES = [\n    {\"name\": \"skew\", \"pool\": HI_LO, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 400},\n    {\"name\": \"zero_fill\", \"pool\": {**_pool(p=(3, 0.5), z=(5, 0.0)), \"neg0\": -0.5, \"none0\": None}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 100},\n    {\"name\": \"zero_unused\", \"pool\": _pool(p=(6, 0.5), z=(10, 0.0)), \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 200},\n    {\"name\": \"all_zero\", \"pool\": {**_pool(z=(10, 0.0)), \"neg0\": -0.3, \"none0\": None}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 50, \"uniform\": True},\n    *({\"name\": name, \"pool\": HI_LO, **extra, \"limit\": LIMIT, \"trials\": 50, \"uniform\": True, \"disabled\": True} for name, extra in DISABLED.items()),\n    {\"name\": \"small_equal\", \"pool\": {\"a\": 0.9, \"b\": 0.5, \"c\": 0.0, \"d\": None, \"e\": 0.2}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 3},\n    {\"name\": \"small_under\", \"pool\": {\"a\": 0.9, \"b\": 0.0, \"c\": 0.4}, \"alpha\": 1.0, \"limit\": LIMIT, \"trials\": 3},\n]\n\n\n@pytest.fixture(scope=\"module\")\ndef draws() -> dict[str, dict[str, list]]:\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", _CHILD, str(SERVER_DIR), json.dumps(CASES)], capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    return json.loads(run.stdout)\n\n\ndef _assert_full_and_distinct(results: list[list[str]]) -> None:\n    for draw in results:\n        assert len(draw) == LIMIT and len(set(draw)) == LIMIT, draw\n\n\ndef test_closer_candidates_are_drawn_clearly_more_often_and_never_twice(draws):\n    results = draws[\"skew\"][\"draws\"]\n    _assert_full_and_distinct(results)\n    hi = sum(vid.startswith(\"hi\") for draw in results for vid in draw)\n    lo = sum(vid.startswith(\"lo\") for draw in results for vid in draw)\n    assert hi >= 3 * lo, (hi, lo)  # expected ~9:1 per slot at alpha 1; 3:1 cannot flake under any seed\n\n\ndef test_zero_weight_candidates_only_fill_what_positive_ones_cannot(draws):\n    filled = draws[\"zero_fill\"][\"draws\"]\n    _assert_full_and_distinct(filled)\n    fill_ids: set[str] = set()\n    for draw in filled:\n        assert {\"p0\", \"p1\", \"p2\"} <= set(draw), draw  # every positive-weight candidate is taken first\n        fill_ids |= set(draw) - {\"p0\", \"p1\", \"p2\"}\n    assert fill_ids == {\"z0\", \"z1\", \"z2\", \"z3\", \"z4\", \"neg0\", \"none0\"}  # the fill spreads over every zero-weight candidate\n    unused = draws[\"zero_unused\"][\"draws\"]\n    _assert_full_and_distinct(unused)\n    assert all(vid.startswith(\"p\") for draw in unused for vid in draw)  # enough positives: zero weights never appear\n\n\ndef test_all_zero_weights_fall_back_to_the_uniform_sample(draws):\n    case = draws[\"all_zero\"]\n    _assert_full_and_distinct(case[\"draws\"])\n    assert case[\"draws\"] == case[\"expected\"]\n\n\n@pytest.mark.parametrize(\"name\", list(DISABLED))\ndef test_a_missing_none_zero_negative_or_nan_alpha_keeps_the_uniform_sample(draws, name):\n    case = draws[name]  # the child's weighted helper raised if called, so reaching here means the uniform branch ran\n    _assert_full_and_distinct(case[\"draws\"])\n    assert case[\"draws\"] == case[\"expected\"]\n\n\n@pytest.mark.parametrize(\"name\", [\"small_equal\", \"small_under\"])\ndef test_a_pool_of_limit_or_fewer_comes_back_whole(draws, name):\n    pool = next(case[\"pool\"] for case in CASES if case[\"name\"] == name)\n    for draw in draws[name][\"draws\"]:\n        assert sorted(draw) == sorted(pool)\n```\n\n**Why each assertion holds, and that none can flake:**\n- **skew.** At alpha 1 each hi entry carries 9 times the weight of a lo entry, so nearly every slot goes to hi. The 3:1 bound sits far below that, and a fixed seed makes the run reproducible anyway.\n- **zero_fill.** There are 3 positive entries for `limit` 5, so every draw takes all three plus 2 of the 7 zero-weight entries (0.0, negative clamped to 0, missing embedding). The chance that 100 trials miss one particular zero entry is about (15/21)^100 \u2248 1e-15.\n- **zero_unused.** There are 6 positive entries for `limit` 5, so the zero group is never reached.\n- **all_zero.** It asserts equality with `random.sample(ordered, 5)`, because the helper consumes no RNG before that sample. All scores are 0.0, so the generator's stable reverse sort leaves pool order unchanged, and `ordered` in the child reproduces it.\n- **Disabled.** The uniform branch is `_random_from_pool(ordered, limit)`, which is `random.sample(ordered, 5)`. The two groups have distinct scores, and within a group the dots are identical, so the stable sort order matches `ordered`.\n- **Small pool.** A pool of `limit` or fewer entries is returned whole.\n\n### Docs\n\n**`LAYER_PARAMS.md`.** Add after line 147:\n\n```markdown\n- `generators.popular.weighted_random_alpha` \u2014 draw-weight exponent when likes exist; 0, negative or missing disables (uniform draw). Set in `home` (1.0); the `upnext` value is inert because the mixer does not run for up-next.\n```\n\nReplace lines 149-150 with:\n\n```markdown\nBehavior: the pool is capped first. With likes and usable embeddings, each entry's `similarity_score` is its best cosine to the liked videos (clamped at 0), and the layer draws `limit` entries without replacement weighted by `similarity_score ** weighted_random_alpha`; zero-weight entries only fill slots the positive-weight ones cannot, uniformly at random. With alpha \u2264 0 or missing, or when every weight is zero, the draw is uniform. Without likes or usable embeddings, the layer takes a uniform random sample of the capped pool. A pool of `limit` or fewer entries is returned whole.\n```\n\n**`OVERVIEW.md` \u00a73, lines 82-83.** Replace with:\n\n```markdown\n  If likes exist, each entry gets `similarity_score` (best cosine to the likes).\n  Selection: with likes, a draw without replacement weighted by `similarity_score ** weighted_random_alpha` (zero weights only fill a shortfall); otherwise a uniform random sample from the pool.\n```\n\n**`OVERVIEW.md` \u00a74, line 109.** Replace with:\n\n```markdown\n- **popular pool**: top by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then likes and views; then caps; if likes exist, drawn weighted by similarity to the likes.\n```\n\n**`PIPELINE_DIAGRAM.md`, line 34.** Replace with the label below. It contains no parentheses or `**`, so the Mermaid syntax stays valid:\n\n```\n    G3 --> H3[Popular pool<br/>similarity-weighted draw if likes]\n```\n\n### Check against plan and requirements\n\n**Pass 1.** Two problems found and fixed:\n- The plan's test import path (`conftest` sys.path) cannot import numpy. The test was moved to an Engine-interpreter child, as the impact inventory directs.\n- The pool stub honoured `count`, which would have forced every case into the small-pool early return. The stub was changed to always return the fixed pool.\n\n**Pass 2.** Every item checks out:\n\n| Requirement | How it is met |\n|---|---|\n| R1: only the final draw changes | Only line 131 changes, plus one config read. The early returns are untouched. |\n| R2: weight is `similarity_score ** alpha` | The helper computes exactly that. |\n| R3: weighted draw without replacement, higher weight more likely | Efraimidis\u2013Spirakis with the top `limit` keys. Covered by the skew test. |\n| R4: zero weights only fill a shortfall, uniformly | Uniform `random.sample` fill. Covered by the zero_fill and zero_unused tests. |\n| R5: all-zero fallback | Exactly `random.sample(candidates, limit)`. The test asserts equality with it. |\n| R6: small pool | The guard returns the pool whole, as today. Covered by the small-pool tests. |\n| R7: disabled | Missing, `None`, 0, negative and NaN all reach `_random_from_pool` unchanged. Tested with the weighted helper patched to refuse. |\n| R8: no epsilon term | None is added. |\n| Config | The key is in `home` and `upnext`, and absent from guest profiles. |\n| Docs | All three docs edits above. |\n| Suite | The existing `test_server_config` count is unaffected. The new tests need only `ENGINE_PY`, which the existing active tests already require. |\n\n**Still open for the operator** (a tradeoff wording issue, not a defect): the plan says behaviour changes on `home` and `upnext`, but the real change is `home` only.",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_16_popular_weighted_random_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_16_popular_weighted_random_phase1.py:101 (via _assert_full_and_distinct at :107, :117, :125): every skew, skew_half, zero_fill and zero_unused draw has exactly 5 distinct ids. :111: hi hits >= 3\u00d7lo at alpha 1.0 and >= 2\u00d7lo at 0.5. :112: lo > 0. :121: p0\u2013p2 are in every zero_fill draw. :123: the zero_fill fill union equals all 7 zero-weight ids. :126: zero_unused (6 positives, plus 0.0, negative and missing-embedding ids) never draws a non-positive id.",
          "expected": "Reference draw: 1773:227 at alpha 1.0 and 1468:532 at 0.5. zero_fill positives appear in 100/100 draws and the fill covers z0\u2013z4, neg0 and none0. zero_unused has 0 non-positive ids.",
          "wrong_implementation": "Today's uniform random.sample: 974:1026 and 1042:958 fail :111; a zero_fill draw missing a positive fails :121; zero_unused draws 663 non-positive ids (neg0 52, none0 54), which fails :126. Treating a missing embedding as weight 1.0 draws none0 185 times, and weighting a negative by abs draws neg0 147 times; both fail :126. A deterministic top-limit pick fails :112 (lo 0). A pool-order fill (always z0, z1) fails :123. Sampling with replacement fails :101."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_16_popular_weighted_random_phase1.py:132: every all_zero draw (every weight 0 at alpha 1.0) equals random.sample(ordered, 5), recomputed under the same per-trial seed. :139, parametrized over missing/None/0/-1.0/NaN on LO_HI: each draw equals random.sample(ordered, 5) under the same seed. :101 via :131, :138 checks each draw is full and distinct.",
          "expected": "Draws are identical to the seeded uniform sample over the similarity-sorted pool: equal_expected True on today's code for all_zero and all five disabled cases.",
          "wrong_implementation": "Several wrong implementations make the list differ within 50 trials: a weighted draw that runs while alpha is disabled (NaN slipping past a `<= 0` guard, or `sim**0 == 1` treated as weighted), extra RNG consumption, or an all-zero pool that takes the weighted/fill path. Sampling the unsorted, low-first pool also differs, because LO_HI inserts lo first."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`."
        },
        {
          "id": "C2",
          "text": "With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_16_popular_weighted_random_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_16_popular_weighted_random_phase1.py  3 failed, 8 passed                     0.0s\n  ---------------------------------------------------\n  total                                                3 failed, 8 passed                     0.4s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_16_popular_weighted_random_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md). It sits near `single-value-pin` but does not meet that entry's `<how_to_spot>`. tests/tmp/test_16_popular_weighted_random_phase1.py:76 and :111\n   SKEW = {\"skew\": (1.0, 3), \"skew_half\": (0.5, 2)}\n   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1\n   The test runs two alpha values, but it checks each one against its own fixed floor and never compares one run with the other. An implementation that uses a fixed exponent whatever alpha is set to would give about 7.8:1 at alpha 0.5. That clears the 2:1 floor, so nothing here shows the output tracks alpha's size. C1 as written only asks that the weighting be \"clearly\" skewed, so this is not blocking. If alpha's size is meant to matter, assert that hi:lo at 1.0 is higher than hi:lo at 0.5.\n\nPREDICTED FAILURE\nAgainst the code as it stands, `get_candidates` ends in the uniform `random.sample(ordered, limit)` and ignores `weighted_random_alpha`. So both SKEW cases fail at line 111 on `assert hi >= SKEW[name][1] * lo` with roughly equal counts (the test's own comment records 974:1026 and 1042:958). The zero-weight test fails at line 121 on `assert positives <= set(draw)`, the first time a uniform draw leaves out one of p0\u2013p2. The all-zero, disabled-alpha and small-pool tests pass, because they describe behaviour the current code already has.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist. It was not read.\n2. `code_under_test` lists engine/server/api/server_config.py (EDITED). A Grep found no `weighted_random_alpha` key in it. The file was not read in full, and the test does not depend on it: it builds its own `config` dict at line 50.\n3. `recommendations.filters.apply_author_instance_caps` was not read. The stub answer assumes that with both caps at 0 it keeps the pool order. The uniform-equality assertions at lines 132 and 139 depend on that order.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a short or overlong draw | CARRIED |\n| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |\n| C1c | must_prove | \"closer candidates appear clearly more often\" | :111 | a uniform sample (1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |\n| C1d | must_prove | zero-weight candidates appear \"only when there are too few positive-weight ones\" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or one displacing a positive (zero_fill) | CARRIED |\n| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |\n| C2a | must_prove | missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG consumption | CARRIED |\n| C2b | must_prove | None alpha \u2192 the same | :139 [disabled_none] | `None` handled as positive, or a crash | CARRIED |\n| C2c | must_prove | zero alpha \u2192 the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that consumes RNG differently | CARRIED |\n| C2d | must_prove | negative alpha \u2192 the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |\n| C2e | must_prove | NaN alpha \u2192 the same | :139 [disabled_nan] | NaN passing a `<= 0` guard and reaching the weights | CARRIED |\n| C2f | must_prove | every weight zero \u2192 the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |\n| D1 | docstring | \"likes path draws by similarity when `weighted_random_alpha` is positive\" | :111 | an alpha-blind draw | CARRIED |\n| D2 | docstring | \"`limit` distinct candidates come back\" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |\n| D3 | docstring | \"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\" | :111 with `SKEW[name][1]` | a weak or absent skew at either alpha | CARRIED |\n| D4 | docstring | \"while the 0.1 group still appears\" | :112 | a deterministic top-`limit` pick | CARRIED |\n| D5a | docstring | 0.0-similarity candidates \"appear only to fill a shortfall\" | :126 | a 0.0 id drawn alongside enough positives | CARRIED |\n| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :121, :123 | nothing: zero_fill has only 3 positives, so a negative or missing-embedding candidate given positive weight is one of 4 weighted items in a draw of 5. All positives still appear (:121) and the fill still covers every id (:123). zero_unused, the only surplus case (:126), has no negative or missing-embedding member | UNCARRIED |\n| D6 | docstring | the fill is \"spread over every one of them\" | :123 | filling from pool order (always z0, z1) | CARRIED |\n| D7 | docstring | \"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\" | :139 | any non-identical draw under the same seed | CARRIED |\n| D8 | docstring | \"or with every weight zero\" | :132 | as C2f | CARRIED |\n| D9 | docstring | \"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\" | :139 on LO_HI (lo inserted first, :73\u201374) | sampling the unsorted pool | CARRIED |\n| D10 | docstring | \"A pool of `limit` or fewer comes back whole\" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |\n| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | a child that failed or never ran being read as results | CARRIED |\n| N1a | name | \"closer candidates are drawn clearly more often\" | :111 | a uniform draw | CARRIED |\n| N1b | name | \"and never twice\" | :101 | sampling with replacement | CARRIED |\n| N2a | name | \"zero weight candidates fill only a shortfall\" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |\n| N2b | name | \"and spread over all of them\" | :123 | a pool-order fill | CARRIED |\n| N3 | name | \"all zero weights draw exactly the uniform sample\" | :132 | any draw other than the seeded sample | CARRIED |\n| N4 | name | \"a missing none zero negative or nan alpha draws exactly the uniform sample\" | :139, parametrized over all five at :135 | any one disabled form leaking into a weighted draw | CARRIED |\n| N5 | name | \"a pool of limit or fewer comes back whole\" | :147 | a partial or padded return | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:3\n   D5b is UNCARRIED. The docstring puts \"negative, missing embedding\" in the zero-weight set that \"appear[s] only to fill a shortfall\". The only case with surplus positives, `zero_unused` (:83, asserted at :126), contains only 0.0-similarity members. `zero_fill` (:75) holds just 3 positives against `limit` 5, so `neg0` or `none0` given positive weight still lets :121 and :123 pass. This clause is in the docstring and not in `must_prove`, so it is not a Critical. Either add `neg0`/`none0` to the `zero_unused` pool or narrow the docstring sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:77\n   The disabled-alpha edges are covered (missing, None, 0, negative, NaN). These inputs are not:\n   - a positive infinite alpha\n   - an empty popular pool\n   - `limit` 0\n\n   The phase's behaviour at those edges is therefore unasserted.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/test_popular_weighted_random.py` as NEW, but that path does not resolve. Whole-claim and bounds were judged from `test_path` and the two engine modules that do resolve.\n2. `fixtures_path` was not supplied. The test's only fixture, `draws` (:90\u201395), is defined in `test_path`, so no conftest was needed to judge independence.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md). It sits near `single-value-pin` but does not meet that entry's `<how_to_spot>`. tests/tmp/test_16_popular_weighted_random_phase1.py:76 and :111\n   SKEW = {\"skew\": (1.0, 3), \"skew_half\": (0.5, 2)}\n   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1\n   The test runs two alpha values, but it checks each one against its own fixed floor and never compares one run with the other. An implementation that uses a fixed exponent whatever alpha is set to would give about 7.8:1 at alpha 0.5. That clears the 2:1 floor, so nothing here shows the output tracks alpha's size. C1 as written only asks that the weighting be \"clearly\" skewed, so this is not blocking. If alpha's size is meant to matter, assert that hi:lo at 1.0 is higher than hi:lo at 0.5.\n\nPREDICTED FAILURE\nAgainst the code as it stands, `get_candidates` ends in the uniform `random.sample(ordered, limit)` and ignores `weighted_random_alpha`. So both SKEW cases fail at line 111 on `assert hi >= SKEW[name][1] * lo` with roughly equal counts (the test's own comment records 974:1026 and 1042:958). The zero-weight test fails at line 121 on `assert positives <= set(draw)`, the first time a uniform draw leaves out one of p0\u2013p2. The all-zero, disabled-alpha and small-pool tests pass, because they describe behaviour the current code already has.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist. It was not read.\n2. `code_under_test` lists engine/server/api/server_config.py (EDITED). A Grep found no `weighted_random_alpha` key in it. The file was not read in full, and the test does not depend on it: it builds its own `config` dict at line 50.\n3. `recommendations.filters.apply_author_instance_caps` was not read. The stub answer assumes that with both caps at 0 it keeps the pool order. The uniform-equality assertions at lines 132 and 139 depend on that order.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a short or overlong draw | CARRIED |\n| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |\n| C1c | must_prove | \"closer candidates appear clearly more often\" | :111 | a uniform sample (1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |\n| C1d | must_prove | zero-weight candidates appear \"only when there are too few positive-weight ones\" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or one displacing a positive (zero_fill) | CARRIED |\n| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |\n| C2a | must_prove | missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG consumption | CARRIED |\n| C2b | must_prove | None alpha \u2192 the same | :139 [disabled_none] | `None` handled as positive, or a crash | CARRIED |\n| C2c | must_prove | zero alpha \u2192 the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that consumes RNG differently | CARRIED |\n| C2d | must_prove | negative alpha \u2192 the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |\n| C2e | must_prove | NaN alpha \u2192 the same | :139 [disabled_nan] | NaN passing a `<= 0` guard and reaching the weights | CARRIED |\n| C2f | must_prove | every weight zero \u2192 the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |\n| D1 | docstring | \"likes path draws by similarity when `weighted_random_alpha` is positive\" | :111 | an alpha-blind draw | CARRIED |\n| D2 | docstring | \"`limit` distinct candidates come back\" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |\n| D3 | docstring | \"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\" | :111 with `SKEW[name][1]` | a weak or absent skew at either alpha | CARRIED |\n| D4 | docstring | \"while the 0.1 group still appears\" | :112 | a deterministic top-`limit` pick | CARRIED |\n| D5a | docstring | 0.0-similarity candidates \"appear only to fill a shortfall\" | :126 | a 0.0 id drawn alongside enough positives | CARRIED |\n| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :121, :123 | nothing: zero_fill has only 3 positives, so a negative or missing-embedding candidate given positive weight is one of 4 weighted items in a draw of 5. All positives still appear (:121) and the fill still covers every id (:123). zero_unused, the only surplus case (:126), has no negative or missing-embedding member | UNCARRIED |\n| D6 | docstring | the fill is \"spread over every one of them\" | :123 | filling from pool order (always z0, z1) | CARRIED |\n| D7 | docstring | \"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\" | :139 | any non-identical draw under the same seed | CARRIED |\n| D8 | docstring | \"or with every weight zero\" | :132 | as C2f | CARRIED |\n| D9 | docstring | \"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\" | :139 on LO_HI (lo inserted first, :73\u201374) | sampling the unsorted pool | CARRIED |\n| D10 | docstring | \"A pool of `limit` or fewer comes back whole\" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |\n| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | a child that failed or never ran being read as results | CARRIED |\n| N1a | name | \"closer candidates are drawn clearly more often\" | :111 | a uniform draw | CARRIED |\n| N1b | name | \"and never twice\" | :101 | sampling with replacement | CARRIED |\n| N2a | name | \"zero weight candidates fill only a shortfall\" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |\n| N2b | name | \"and spread over all of them\" | :123 | a pool-order fill | CARRIED |\n| N3 | name | \"all zero weights draw exactly the uniform sample\" | :132 | any draw other than the seeded sample | CARRIED |\n| N4 | name | \"a missing none zero negative or nan alpha draws exactly the uniform sample\" | :139, parametrized over all five at :135 | any one disabled form leaking into a weighted draw | CARRIED |\n| N5 | name | \"a pool of limit or fewer comes back whole\" | :147 | a partial or padded return | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:3\n   D5b is UNCARRIED. The docstring puts \"negative, missing embedding\" in the zero-weight set that \"appear[s] only to fill a shortfall\". The only case with surplus positives, `zero_unused` (:83, asserted at :126), contains only 0.0-similarity members. `zero_fill` (:75) holds just 3 positives against `limit` 5, so `neg0` or `none0` given positive weight still lets :121 and :123 pass. This clause is in the docstring and not in `must_prove`, so it is not a Critical. Either add `neg0`/`none0` to the `zero_unused` pool or narrow the docstring sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:77\n   The disabled-alpha edges are covered (missing, None, 0, negative, NaN). These inputs are not:\n   - a positive infinite alpha\n   - an empty popular pool\n   - `limit` 0\n\n   The phase's behaviour at those edges is therefore unasserted.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/test_popular_weighted_random.py` as NEW, but that path does not resolve. Whole-claim and bounds were judged from `test_path` and the two engine modules that do resolve.\n2. `fixtures_path` was not supplied. The test's only fixture, `draws` (:90\u201395), is defined in `test_path`, so no conftest was needed to judge independence.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "with likes and positive alpha, returns `limit` candidates",
            "assertion": ":101 (via :107, :117, :125)",
            "excludes": "a short or overlong draw",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the candidates are distinct",
            "assertion": ":101 `len(set(draw)) == LIMIT`",
            "excludes": "drawing with replacement",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"closer candidates appear clearly more often\"",
            "assertion": ":111",
            "excludes": "a uniform sample (1:1 against a 3:1 / 2:1 floor), or alpha ignored",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "zero-weight candidates appear \"only when there are too few positive-weight ones\"",
            "assertion": ":126, :121",
            "excludes": "a zero-weight id drawn while positives remain (zero_unused), or one displacing a positive (zero_fill)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "zero-weight candidates do fill a shortfall up to `limit`",
            "assertion": ":117 (:101 on zero_fill, 3 positives, limit 5)",
            "excludes": "dropping zero-weight candidates and returning fewer than `limit`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed",
            "assertion": ":139 [disabled_missing]",
            "excludes": "a weighted draw when the key is absent, or extra RNG consumption",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "None alpha \u2192 the same",
            "assertion": ":139 [disabled_none]",
            "excludes": "`None` handled as positive, or a crash",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "zero alpha \u2192 the same",
            "assertion": ":139 [disabled_zero]",
            "excludes": "`sim**0 == 1` taken as a weighted path that consumes RNG differently",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "negative alpha \u2192 the same",
            "assertion": ":139 [disabled_negative]",
            "excludes": "an inverse-weighted draw",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "NaN alpha \u2192 the same",
            "assertion": ":139 [disabled_nan]",
            "excludes": "NaN passing a `<= 0` guard and reaching the weights",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "every weight zero \u2192 the same",
            "assertion": ":132",
            "excludes": "a weighted path with all-zero keys, or a fill in pool order",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"likes path draws by similarity when `weighted_random_alpha` is positive\"",
            "assertion": ":111",
            "excludes": "an alpha-blind draw",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"`limit` distinct candidates come back\" at alpha 1.0 or 0.5",
            "assertion": ":101 via :107",
            "excludes": "short or duplicated draws",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\"",
            "assertion": ":111 with `SKEW[name][1]`",
            "excludes": "a weak or absent skew at either alpha",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"while the 0.1 group still appears\"",
            "assertion": ":112",
            "excludes": "a deterministic top-`limit` pick",
            "status": "CARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "0.0-similarity candidates \"appear only to fill a shortfall\"",
            "assertion": ":126",
            "excludes": "a 0.0 id drawn alongside enough positives",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall",
            "assertion": ":121, :123",
            "excludes": "nothing: zero_fill has only 3 positives, so a negative or missing-embedding candidate given positive weight is one of 4 weighted items in a draw of 5. All positives still appear (:121) and the fill still covers every id (:123). zero_unused, the only surplus case (:126), has no negative or missing-embedding member",
            "status": "UNCARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "the fill is \"spread over every one of them\"",
            "assertion": ":123",
            "excludes": "filling from pool order (always z0, z1)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\"",
            "assertion": ":139",
            "excludes": "any non-identical draw under the same seed",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"or with every weight zero\"",
            "assertion": ":132",
            "excludes": "as C2f",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\"",
            "assertion": ":139 on LO_HI (lo inserted first, :73\u201374)",
            "excludes": "sampling the unsorted pool",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"A pool of `limit` or fewer comes back whole\"",
            "assertion": ":147",
            "excludes": "truncating, dropping zero-weight or None-embedding members, duplicating",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "every case runs in one Engine-interpreter child, reseeded per trial",
            "assertion": ":94",
            "excludes": "a child that failed or never ran being read as results",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"closer candidates are drawn clearly more often\"",
            "assertion": ":111",
            "excludes": "a uniform draw",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "\"and never twice\"",
            "assertion": ":101",
            "excludes": "sampling with replacement",
            "status": "CARRIED"
          },
          {
            "id": "N2a",
            "source": "name",
            "clause": "\"zero weight candidates fill only a shortfall\"",
            "assertion": ":121, :126",
            "excludes": "zero-weight ids drawn while positives are available",
            "status": "CARRIED"
          },
          {
            "id": "N2b",
            "source": "name",
            "clause": "\"and spread over all of them\"",
            "assertion": ":123",
            "excludes": "a pool-order fill",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"all zero weights draw exactly the uniform sample\"",
            "assertion": ":132",
            "excludes": "any draw other than the seeded sample",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a missing none zero negative or nan alpha draws exactly the uniform sample\"",
            "assertion": ":139, parametrized over all five at :135",
            "excludes": "any one disabled form leaking into a weighted draw",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"a pool of limit or fewer comes back whole\"",
            "assertion": ":147",
            "excludes": "a partial or padded return",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; it is nearest to single-value-pin (rules/shape.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:111\n   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1\n   The test runs alpha 1.0 and alpha 0.5, but each is checked alone against its own ratio (3:1 and 2:1). Nothing checks that the two draws differ from each other. An implementation that ignores alpha and always weights as if alpha were 1.0 would give about 7.8:1 at both values and pass both. That does not break a stated entry: this is not one input, and C1 does not say the skew must follow alpha. If alpha is meant to control how strong the skew is, asserting that alpha 1.0 skews more than alpha 0.5 would make that part of the gate, following the entry's `<alternatives>`.\n\nPREDICTED FAILURE\nAgainst the current code, which only ever calls `random.sample(ordered, limit)`, the test should fail in two places:\n- `test_closer_candidates_are_drawn_clearly_more_often_and_never_twice[skew]` and `[skew_half]` should fail at line 111. `hi >= SKEW[name][1] * lo` does not hold because the uniform draw gives about 974:1026 and 1042:958.\n- `test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them` should fail at line 121. `positives <= set(draw)` does not hold because a uniform 5-of-10 draw leaves out some of p0\u2013p2.\n\nThese tests should pass against the current code:\n- `test_all_zero_weights_draw_exactly_the_uniform_sample`\n- the five `test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample` cases\n- the two `test_a_pool_of_limit_or_fewer_comes_back_whole` cases\n\nThat is expected: C2 says the old draw must stay the same, so these tests pass on the old code. They still catch wrong implementations: weighting that leaks into the disabled or all-zero path, or sampling in pool order instead of similarity order. They would fail on either.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist yet. Nothing in it was assessed.\n2. Whether `ENGINE_PY` (engine/.pixi/envs/default/bin/python) exists was not checked. If it is missing, the `draws` fixture fails at line 92 before any test assertion runs, and the prediction above does not hold.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a draw that is too short or too long | CARRIED |\n| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |\n| C1c | must_prove | \"closer candidates appear clearly more often\" | :111 | a uniform sample (about 1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |\n| C1d | must_prove | zero-weight candidates appear \"only when there are too few positive-weight ones\" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or a zero-weight id pushing out a positive (zero_fill) | CARRIED |\n| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |\n| C2a | must_prove | missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG use | CARRIED |\n| C2b | must_prove | None alpha \u2192 the same | :139 [disabled_none] | `None` treated as positive, or a crash | CARRIED |\n| C2c | must_prove | zero alpha \u2192 the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that uses the RNG differently | CARRIED |\n| C2d | must_prove | negative alpha \u2192 the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |\n| C2e | must_prove | NaN alpha \u2192 the same | :139 [disabled_nan] | NaN getting past a `<= 0` guard and reaching the weights | CARRIED |\n| C2f | must_prove | every weight zero \u2192 the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |\n| D1 | docstring | \"likes path draws by similarity when `weighted_random_alpha` is positive\" | :111 | a draw that ignores alpha | CARRIED |\n| D2 | docstring | \"`limit` distinct candidates come back\" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |\n| D3 | docstring | \"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\" | :111 with `SKEW[name][1]` | a weak or missing skew at either alpha | CARRIED |\n| D4 | docstring | \"while the 0.1 group still appears\" | :112 | a fixed top-`limit` pick | CARRIED |\n| D5a | docstring | 0.0-similarity candidates \"appear only to fill a shortfall\" | :126 | a 0.0 id drawn when there are enough positives | CARRIED |\n| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :126 (zero_unused pool at :83 now includes `neg0` -0.5 and `none0` None) | a negative or missing-embedding candidate given positive weight: it would be one of 8 weighted items for 5 slots over 200 trials, and :126 rejects any non-`p` id | CARRIED |\n| D6 | docstring | the fill is \"spread over every one of them\" | :123 | filling in pool order (always z0, z1) | CARRIED |\n| D7 | docstring | \"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\" | :139 | any draw that differs under the same seed | CARRIED |\n| D8 | docstring | \"or with every weight zero\" | :132 | same as C2f | CARRIED |\n| D9 | docstring | \"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\" | :139 on LO_HI (lo inserted first, :73\u201374) | sampling the unsorted pool | CARRIED |\n| D10 | docstring | \"A pool of `limit` or fewer comes back whole\" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |\n| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | reading a child that failed or never ran as if it gave results | CARRIED |\n| N1a | name | \"closer candidates are drawn clearly more often\" | :111 | a uniform draw | CARRIED |\n| N1b | name | \"and never twice\" | :101 | sampling with replacement | CARRIED |\n| N2a | name | \"zero weight candidates fill only a shortfall\" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |\n| N2b | name | \"and spread over all of them\" | :123 | a fill in pool order | CARRIED |\n| N3 | name | \"all zero weights draw exactly the uniform sample\" | :132 | any draw other than the seeded sample | CARRIED |\n| N4 | name | \"a missing none zero negative or nan alpha draws exactly the uniform sample\" | :139, parametrized over all five at :135 | any one disabled form slipping into a weighted draw | CARRIED |\n| N5 | name | \"a pool of limit or fewer comes back whole\" | :147 | a partial or padded return | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_16_popular_weighted_random_phase1.py:83\n   D5b, UNCARRIED in the ledger, is now carried because an assertion was added: the zero_unused pool at :83 now includes `neg0` (-0.5) and `none0` (None). The docstring sentence was not narrowed, and :126 now excludes a positive weight on either member.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not resolve. It could not be read or compared with the file under audit.\n2. `code_under_test` lists engine/server/api/server_config.py (EDITED), but it contains no `weighted_random_alpha`. I could not judge from it how a real config supplies alpha or its default. The test passes `config` directly into `get_candidates` (tests/tmp/test_16_popular_weighted_random_phase1.py:50\u201352, :59), so the verdict stands on that seam alone.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; it is nearest to single-value-pin (rules/shape.md) \u2014 tests/tmp/test_16_popular_weighted_random_phase1.py:111\n   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1\n   The test runs alpha 1.0 and alpha 0.5, but each is checked alone against its own ratio (3:1 and 2:1). Nothing checks that the two draws differ from each other. An implementation that ignores alpha and always weights as if alpha were 1.0 would give about 7.8:1 at both values and pass both. That does not break a stated entry: this is not one input, and C1 does not say the skew must follow alpha. If alpha is meant to control how strong the skew is, asserting that alpha 1.0 skews more than alpha 0.5 would make that part of the gate, following the entry's `<alternatives>`.\n\nPREDICTED FAILURE\nAgainst the current code, which only ever calls `random.sample(ordered, limit)`, the test should fail in two places:\n- `test_closer_candidates_are_drawn_clearly_more_often_and_never_twice[skew]` and `[skew_half]` should fail at line 111. `hi >= SKEW[name][1] * lo` does not hold because the uniform draw gives about 974:1026 and 1042:958.\n- `test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them` should fail at line 121. `positives <= set(draw)` does not hold because a uniform 5-of-10 draw leaves out some of p0\u2013p2.\n\nThese tests should pass against the current code:\n- `test_all_zero_weights_draw_exactly_the_uniform_sample`\n- the five `test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample` cases\n- the two `test_a_pool_of_limit_or_fewer_comes_back_whole` cases\n\nThat is expected: C2 says the old draw must stay the same, so these tests pass on the old code. They still catch wrong implementations: weighting that leaks into the disabled or all-zero path, or sampling in pool order instead of similarity order. They would fail on either.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist yet. Nothing in it was assessed.\n2. Whether `ENGINE_PY` (engine/.pixi/envs/default/bin/python) exists was not checked. If it is missing, the `draws` fixture fails at line 92 before any test assertion runs, and the prediction above does not hold.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a draw that is too short or too long | CARRIED |\n| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |\n| C1c | must_prove | \"closer candidates appear clearly more often\" | :111 | a uniform sample (about 1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |\n| C1d | must_prove | zero-weight candidates appear \"only when there are too few positive-weight ones\" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or a zero-weight id pushing out a positive (zero_fill) | CARRIED |\n| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |\n| C2a | must_prove | missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG use | CARRIED |\n| C2b | must_prove | None alpha \u2192 the same | :139 [disabled_none] | `None` treated as positive, or a crash | CARRIED |\n| C2c | must_prove | zero alpha \u2192 the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that uses the RNG differently | CARRIED |\n| C2d | must_prove | negative alpha \u2192 the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |\n| C2e | must_prove | NaN alpha \u2192 the same | :139 [disabled_nan] | NaN getting past a `<= 0` guard and reaching the weights | CARRIED |\n| C2f | must_prove | every weight zero \u2192 the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |\n| D1 | docstring | \"likes path draws by similarity when `weighted_random_alpha` is positive\" | :111 | a draw that ignores alpha | CARRIED |\n| D2 | docstring | \"`limit` distinct candidates come back\" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |\n| D3 | docstring | \"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\" | :111 with `SKEW[name][1]` | a weak or missing skew at either alpha | CARRIED |\n| D4 | docstring | \"while the 0.1 group still appears\" | :112 | a fixed top-`limit` pick | CARRIED |\n| D5a | docstring | 0.0-similarity candidates \"appear only to fill a shortfall\" | :126 | a 0.0 id drawn when there are enough positives | CARRIED |\n| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :126 (zero_unused pool at :83 now includes `neg0` -0.5 and `none0` None) | a negative or missing-embedding candidate given positive weight: it would be one of 8 weighted items for 5 slots over 200 trials, and :126 rejects any non-`p` id | CARRIED |\n| D6 | docstring | the fill is \"spread over every one of them\" | :123 | filling in pool order (always z0, z1) | CARRIED |\n| D7 | docstring | \"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\" | :139 | any draw that differs under the same seed | CARRIED |\n| D8 | docstring | \"or with every weight zero\" | :132 | same as C2f | CARRIED |\n| D9 | docstring | \"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\" | :139 on LO_HI (lo inserted first, :73\u201374) | sampling the unsorted pool | CARRIED |\n| D10 | docstring | \"A pool of `limit` or fewer comes back whole\" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |\n| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | reading a child that failed or never ran as if it gave results | CARRIED |\n| N1a | name | \"closer candidates are drawn clearly more often\" | :111 | a uniform draw | CARRIED |\n| N1b | name | \"and never twice\" | :101 | sampling with replacement | CARRIED |\n| N2a | name | \"zero weight candidates fill only a shortfall\" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |\n| N2b | name | \"and spread over all of them\" | :123 | a fill in pool order | CARRIED |\n| N3 | name | \"all zero weights draw exactly the uniform sample\" | :132 | any draw other than the seeded sample | CARRIED |\n| N4 | name | \"a missing none zero negative or nan alpha draws exactly the uniform sample\" | :139, parametrized over all five at :135 | any one disabled form slipping into a weighted draw | CARRIED |\n| N5 | name | \"a pool of limit or fewer comes back whole\" | :147 | a partial or padded return | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_16_popular_weighted_random_phase1.py:83\n   D5b, UNCARRIED in the ledger, is now carried because an assertion was added: the zero_unused pool at :83 now includes `neg0` (-0.5) and `none0` (None). The docstring sentence was not narrowed, and :126 now excludes a positive weight on either member.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not resolve. It could not be read or compared with the file under audit.\n2. `code_under_test` lists engine/server/api/server_config.py (EDITED), but it contains no `weighted_random_alpha`. I could not judge from it how a real config supplies alpha or its default. The test passes `config` directly into `get_candidates` (tests/tmp/test_16_popular_weighted_random_phase1.py:50\u201352, :59), so the verdict stands on that seam alone.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "with likes and positive alpha, returns `limit` candidates",
            "assertion": ":101 (via :107, :117, :125)",
            "excludes": "a draw that is too short or too long",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the candidates are distinct",
            "assertion": ":101 `len(set(draw)) == LIMIT`",
            "excludes": "drawing with replacement",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"closer candidates appear clearly more often\"",
            "assertion": ":111",
            "excludes": "a uniform sample (about 1:1 against a 3:1 / 2:1 floor), or alpha ignored",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "zero-weight candidates appear \"only when there are too few positive-weight ones\"",
            "assertion": ":126, :121",
            "excludes": "a zero-weight id drawn while positives remain (zero_unused), or a zero-weight id pushing out a positive (zero_fill)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "zero-weight candidates do fill a shortfall up to `limit`",
            "assertion": ":117 (:101 on zero_fill, 3 positives, limit 5)",
            "excludes": "dropping zero-weight candidates and returning fewer than `limit`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "missing alpha \u2192 exactly `random.sample(ordered, limit)` under the same seed",
            "assertion": ":139 [disabled_missing]",
            "excludes": "a weighted draw when the key is absent, or extra RNG use",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "None alpha \u2192 the same",
            "assertion": ":139 [disabled_none]",
            "excludes": "`None` treated as positive, or a crash",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "zero alpha \u2192 the same",
            "assertion": ":139 [disabled_zero]",
            "excludes": "`sim**0 == 1` taken as a weighted path that uses the RNG differently",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "negative alpha \u2192 the same",
            "assertion": ":139 [disabled_negative]",
            "excludes": "an inverse-weighted draw",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "NaN alpha \u2192 the same",
            "assertion": ":139 [disabled_nan]",
            "excludes": "NaN getting past a `<= 0` guard and reaching the weights",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "every weight zero \u2192 the same",
            "assertion": ":132",
            "excludes": "a weighted path with all-zero keys, or a fill in pool order",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"likes path draws by similarity when `weighted_random_alpha` is positive\"",
            "assertion": ":111",
            "excludes": "a draw that ignores alpha",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"`limit` distinct candidates come back\" at alpha 1.0 or 0.5",
            "assertion": ":101 via :107",
            "excludes": "short or duplicated draws",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)\"",
            "assertion": ":111 with `SKEW[name][1]`",
            "excludes": "a weak or missing skew at either alpha",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"while the 0.1 group still appears\"",
            "assertion": ":112",
            "excludes": "a fixed top-`limit` pick",
            "status": "CARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "0.0-similarity candidates \"appear only to fill a shortfall\"",
            "assertion": ":126",
            "excludes": "a 0.0 id drawn when there are enough positives",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall",
            "assertion": ":126 (zero_unused pool at :83 now includes `neg0` -0.5 and `none0` None)",
            "excludes": "a negative or missing-embedding candidate given positive weight: it would be one of 8 weighted items for 5 slots over 200 trials, and :126 rejects any non-`p` id",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "the fill is \"spread over every one of them\"",
            "assertion": ":123",
            "excludes": "filling in pool order (always z0, z1)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"alpha missing, None, 0, -1.0 or NaN \u2026 each draw equals `random.sample(ordered, limit)`\"",
            "assertion": ":139",
            "excludes": "any draw that differs under the same seed",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"or with every weight zero\"",
            "assertion": ":132",
            "excludes": "same as C2f",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order\"",
            "assertion": ":139 on LO_HI (lo inserted first, :73\u201374)",
            "excludes": "sampling the unsorted pool",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"A pool of `limit` or fewer comes back whole\"",
            "assertion": ":147",
            "excludes": "truncating, dropping zero-weight or None-embedding members, duplicating",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "every case runs in one Engine-interpreter child, reseeded per trial",
            "assertion": ":94",
            "excludes": "reading a child that failed or never ran as if it gave results",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"closer candidates are drawn clearly more often\"",
            "assertion": ":111",
            "excludes": "a uniform draw",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "\"and never twice\"",
            "assertion": ":101",
            "excludes": "sampling with replacement",
            "status": "CARRIED"
          },
          {
            "id": "N2a",
            "source": "name",
            "clause": "\"zero weight candidates fill only a shortfall\"",
            "assertion": ":121, :126",
            "excludes": "zero-weight ids drawn while positives are available",
            "status": "CARRIED"
          },
          {
            "id": "N2b",
            "source": "name",
            "clause": "\"and spread over all of them\"",
            "assertion": ":123",
            "excludes": "a fill in pool order",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"all zero weights draw exactly the uniform sample\"",
            "assertion": ":132",
            "excludes": "any draw other than the seeded sample",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a missing none zero negative or nan alpha draws exactly the uniform sample\"",
            "assertion": ":139, parametrized over all five at :135",
            "excludes": "any one disabled form slipping into a weighted draw",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"a pool of limit or fewer comes back whole\"",
            "assertion": ":147",
            "excludes": "a partial or padded return",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/api/recommendations/candidates/popular_videos.py: in `_weighted_from_pool`, the all-zero exit and the small-pool exit (`len(scored) <= limit`) are now one `if not positive or len(scored) <= limit:` that returns `_random_from_pool` over the similarity-ordered list. `_random_from_pool` already returns a pool of `limit` or fewer whole, so the separate list comprehension and early return are gone. The branch comment now explains why both cases go there.\n</refactors>\n\n<left_out>\nMoving the `weighted_random_alpha` read up to join the other config reads at the top of `get_candidates`, as the impacts step suggested. It is not a pure refactor: a non-numeric alpha would then raise `float()` on the no-likes and no-embedding paths too, where today it never gets read. The three copies of the timing-log-then-`_random_from_pool` early return in `get_candidates` were there before this build and this phase did not touch them, so pulling them into a helper would widen the diff past the approved scope. The odd import order (`import random` and `from time import perf_counter` sit below numpy) is also older than this build, so I left it alone. I made no change to `server_config.py`: the two added keys and the one comment on `home` are already as small as they can be. I also had no way to delete `tests/tmp/probe_16_refactor_equivalence.py` (there is no delete tool), so I emptied it. The workflow or the operator should remove it.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI checked the merge with a probe rather than the gating suite. It copied the old and new `_weighted_from_pool` side by side and ran them on 20,000 random cases (score 0, scores that underflow under alpha 200, pools smaller and larger than `limit`), each pair under the same seed. The returned lists and the RNG state afterwards were identical every time, so the refactor keeps the byte-for-byte uniform fallback the C2 checkpoint needs. The call site stays a module-global `_weighted_from_pool`, so the checkpoint's refusing patch still intercepts it. I did not run the gating test `tests/tmp/test_16_popular_weighted_random_phase1.py` myself; the workflow's run is the one that confirms it.\n</observation>"
}
```
dev-flow:state -->

## 2026-09-28 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 27 test groups (26 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

When a visitor has likes, the popular layer of the recommendation feed should favour popular videos that are similar to what the visitor liked. Today `PopularVideosGenerator.get_candidates` (`engine/server/api/recommendations/candidates/popular_videos.py`) scores every pool entry by its maximum cosine similarity to the liked vectors and sorts by it. It then calls `_random_from_pool`, which does `random.sample` over the whole pool, so the similarity scoring has almost no effect on which videos come out. This must land before `17-feed-modes`, which exposes popular as a user-facing mode.

### Context the later steps need

- The mixer (`engine/server/api/recommendations/mixer.py`) takes the layer's output, optionally shuffles it (`shuffle: True` in every profile), then re-sorts each layer by the unified `score`. Only **which** candidates the layer returns matters, not their order.
- The layer is asked for few candidates from a big pool. In `home` it is roughly batch 48 × overfetch 1 × gather_ratio 0.1 ≈ 5 candidates from a `DEFAULT_POPULAR_POOL_SIZE` = 5000 pool (after the author/instance caps).
- `_max_similarity` already clamps the similarity to be at least 0 (it returns 0.0 when the best dot product is ≤ 0). Entries with no embedding or a zero-norm vector get `similarity_score` 0.0.
- There is a precedent for this kind of draw: `_draw_page` in `engine/server/api/handlers/similar.py` does weighted sampling without replacement (Efraimidis–Spirakis: key = log(u)/weight, largest keys win, zero-weight rows only fill what positive rows cannot). Whether to reuse it, share it, or write a local equivalent is a design decision for Step 2.

### Functional requirements

1. **Scope of the change.** Only the likes path of `PopularVideosGenerator.get_candidates` changes: the final draw after scoring (currently `_random_from_pool(ordered, limit)`). The paths with no likes, no liked/pool embeddings, or no usable liked vectors stay exactly as they are (plain `random.sample` via `_random_from_pool`). Fetching the pool, the author/instance caps, scoring, and setting `entry["similarity_score"]` do not change.
2. **Weight.** Each candidate's draw weight is `similarity_score ** alpha`, where `alpha` is the configured `weighted_random_alpha`. `similarity_score` is already ≥ 0, so this equals the issue's `max(similarity, 0.0) ** alpha`.
3. **Weighted draw.** When `alpha > 0` and the pool (after caps) is larger than `limit`, return `limit` candidates chosen by weighted random sampling without replacement. Each candidate's chance goes up with its weight, and none is returned twice.
4. **Zero weights.** Candidates with weight 0 are drawn only when the positive-weight candidates number fewer than `limit`. The remaining slots are filled from the zero-weight candidates uniformly at random.
5. **All-zero fallback.** If every candidate's weight is 0, the result is a plain uniform `random.sample(pool, limit)`, the same as today.
6. **Small pool.** When the pool has `limit` or fewer candidates, all of them are returned, the same as today.
7. **Disabled.** When `weighted_random_alpha` is missing, `None`, 0, or negative, the likes path behaves exactly as today: a uniform `random.sample` over the scored pool.
8. **No epsilon/diversity term.** This is a deliberate choice. The consequence is that, with likes and weighting on, popular videos with zero similarity to the likes almost never come out of the popular layer. Variety still comes from the random, fresh and explore layers.

### Configuration

- New per-profile key `generators.popular.weighted_random_alpha` (float) in `RECOMMENDATION_PIPELINE` in `engine/server/api/server_config.py`. It sits next to the existing `generators.popular.*` keys and is read inside the generator from its `config` dict, following the file's existing pattern (for example `float(config.get("weighted_random_alpha") or 0.0)`). The issue's name `popular.weighted_random_alpha` means this key.
- Default value **1.0** in the `home` and `upnext` profiles (operator decision). With it, the feed's behaviour changes on deploy.
- The `guest_home` and `guest_upnext` profiles are not changed. They are only picked when there are no likes, and on that path the weighting never runs.
- There are no environment-variable or CLI overrides.

### Documentation

- `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, section "popular Layer": list `generators.popular.weighted_random_alpha` and describe the behaviour correctly. With likes, the layer draws by weight `similarity ** alpha`; with alpha 0 or less, or all weights zero, it draws uniformly. Without likes, it takes a uniform random sample of the pool. This replaces the current inaccurate "otherwise it is returned as-is".
- `engine/server/api/recommendations/docs/OVERVIEW.md`: the popular entries (layer description around line 78 and pool summary around line 109) must mention the similarity-weighted draw.

### Tests

- New tests in `tests/active/` that call `PopularVideosGenerator` directly with stub deps (stubbed `fetch_popular_videos`, `fetch_recent_likes`, `fetch_embeddings_by_ids`, `like_key`, and a server object with `db` and `db_lock`). They cover:
  - with alpha > 0, higher-similarity candidates are picked clearly more often than lower-similarity ones, and no candidate is returned twice;
  - zero-weight candidates appear only when the positive-weight candidates cannot fill `limit`;
  - all weights zero falls back to a uniform draw that still returns `limit` distinct candidates;
  - alpha 0 (or a missing key) behaves as today's uniform sample;
  - a pool of `limit` or fewer returns every candidate.
- The tests must be deterministic: seed or patch the random source, or use a trial count and bounds that cannot flake.

### Baseline suite state

Before the build, the suite exited 0 (baseline variant: false). The build must leave the suite green.

### Out of scope

- Epsilon/diversity mixing inside the popular layer.
- Changing the no-likes popular path, the pool query (`fetch_popular_videos`), the caps, the scoring formula, or the mixer.
- Guest profiles, and any user-facing feed mode (that is `17-feed-modes`).

### conflicts

The issue names the config parameter `popular.weighted_random_alpha`, but the tree keeps layer parameters per profile under `RECOMMENDATION_PIPELINE["profiles"][<profile>]["generators"]["popular"]` in `engine/server/api/server_config.py`. Resolved: the key is `generators.popular.weighted_random_alpha` in each profile.
The issue says "0 = disabled", which could suggest shipping it off by default. The operator chose default 1.0 in `home` and `upnext`, so feed behaviour changes on deploy.
`engine/server/api/recommendations/docs/LAYER_PARAMS.md` ("popular Layer") says that without likes the pool "is returned as-is", but `popular_videos.py` actually returns `random.sample(pool, limit)` on that path. Resolved: the docs will be corrected to match the code.
`LAYER_PARAMS.md` ("Up-next Params") says up-next does not run the generator layers, yet the `upnext` profile carries a `generators.popular` block. The alpha default is still set there, so it takes effect wherever that profile's generators run; Step 2/3 should confirm whether that block is live.

## 2026-09-28 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

The change stays inside `engine/server/api/recommendations/candidates/popular_videos.py`, plus one config key per profile, two doc edits and one new test file.

In `get_candidates`, the three early-return paths (no likes, no liked or pool embeddings, no usable liked vectors) keep calling `_random_from_pool(pool, limit)`. The pool fetch, the author/instance caps, the scoring loop, the `entry["similarity_score"]` assignment, the existing sort and the timing logs also stay as they are. Only the last line of the likes path changes. It reads `alpha` from the generator's `config` dict in the file's existing style (`float(config.get("weighted_random_alpha") or 0.0)`). If `alpha` is 0 or less it calls `_random_from_pool(ordered, limit)` exactly as today. Otherwise it calls a new module-level helper next to `_random_from_pool`, something like `_weighted_from_pool(candidates, limit, alpha)`.

The helper works like this:

- **Small pool.** If the pool has `limit` or fewer entries, it returns all of them, the same as `_random_from_pool` does today (requirement 6).
- **Weights.** It computes each entry's weight as `similarity_score ** alpha` (requirement 2). The score is already clamped to at least 0, so no extra clamp is needed.
- **Split.** It splits the pool into positive-weight entries and zero-weight entries.
- **All zero.** If there are no positive weights, it returns `random.sample(candidates, limit)`. That is the same call as today (requirement 5).
- **Weighted draw.** Otherwise it runs Efraimidis–Spirakis over the positive entries. Each one gets `u = 1 - random.random()`, so `u` is in (0, 1], and the key `log(u) / weight`. The `limit` largest keys win. This is weighted sampling without replacement: an entry's chance of being kept rises with its weight, and none can come back twice (requirement 3).
- **Fill.** If fewer than `limit` entries have positive weight, the gap is filled by `random.sample` over the zero-weight entries. Zero-weight entries therefore appear only when the positive ones run out, and the fill is uniform (requirement 4).

The output order does not matter because the mixer shuffles and then re-sorts by the unified score. So the helper returns the list as it comes and does no final sort.

How each requirement is met:

- Requirement 1: only the final draw of the likes path is replaced.
- Requirement 7: a missing key, `None`, 0 or a negative value all go through `or 0.0` and the `<= 0` check to the existing uniform call. A NaN also fails the `> 0` test, so it is disabled too.
- Requirement 8: there is no epsilon term.

The randomness uses the stdlib `random` module, which the file already imports. `numpy` is not used for this, so tests can make the draw deterministic with `random.seed` or by patching `popular_videos.random`.

**Configuration.** Add `"weighted_random_alpha": 1.0` to `generators.popular` in the `home` and `upnext` profiles in `server_config.py`, next to `pool_size` and the caps. `guest_home` and `guest_upnext` stay unchanged. I checked `resolve_profile_config_with_guest`: it picks a profile whole and does no merging, and the mixer passes `generator_configs.get(name, {})` to the generator. So the key reaches the generator only in those two profiles, and there is no inheritance to worry about.

**Docs.**

- `LAYER_PARAMS.md`, "popular Layer": list the key and replace "otherwise it is returned as-is". The new text says: with likes, the layer draws by weight `similarity ** alpha` without replacement, and zero-weight entries only fill a shortfall. With alpha 0 or less, or all weights zero, it draws uniformly. Without likes (or without usable embeddings), it takes a uniform random sample of the capped pool.
- `OVERVIEW.md`: the popular layer description (around line 78) and the pool summary (around line 109) get one clause each about the similarity-weighted draw.

**Tests.** A new file under `tests/active/`, set up for imports the same way as the existing active tests (the `conftest.py` sys.path setup). It builds `PopularVideosGenerator` with a `PopularVideosDeps` of stubs:

- `fetch_popular_videos` returns a fixed pool.
- `fetch_recent_likes` returns one or no like.
- `fetch_embeddings_by_ids` returns hand-built vectors, so each entry's cosine similarity to the like is chosen exactly (0, low, high).
- `like_key` reads an id.

The server is a `SimpleNamespace` with `db=None` and `db_lock=threading.Lock()`. The caps are set to 0 so they do not interfere.

Every test seeds `random` (or patches it) before calling. The frequency test runs a fixed number of trials under a fixed seed, with loose bounds, e.g. the high-similarity group is picked at least twice as often as the low group. With a fixed seed the result is fully reproducible, and the bounds are wide enough to survive a change of seed. The cases are exactly the five listed in the requirements. Each asserts distinct keys and `len == limit` where that applies. The zero-weight case uses fewer positive entries than `limit` and checks two things: every positive entry is present, and zero-weight entries appear only in that case.

### Alternatives considered

- **Import `_draw_page` from `handlers/similar.py`.** Rejected, for four reasons:
  - It would make the recommendations package depend on a handler module, which is the wrong direction.
  - It gets the weight from `_draw_weight(row)` (the personalized score), not from `similarity ** alpha`.
  - It fills zero-weight rows in window order, not uniformly, which breaks requirement 4.
  - It re-sorts its output and carries seeded-hash machinery that this layer does not need.
- **Pull a shared weighted-sampling helper into a common module used by both.** Rejected for now. The two call sites differ in weight source, zero-fill semantics (window order vs uniform), seeding (blake2b per key vs process RNG) and output order. A shared helper would need parameters for each of those differences, which is speculative generality for two callers. It would also touch the up-next handler, which is out of scope. This is a deliberate duplication of about ten lines. If a third caller appears, both can be moved onto a helper that takes a weight function and a fill policy.
- **`numpy.random.Generator.choice(replace=False, p=...)`.** Rejected. It raises when fewer entries have non-zero probability than the requested size, so the zero-fill would still need its own code. It also needs normalised probabilities, and it uses a different RNG from `random`, which makes the test seeding harder.
- **`random.choices` with weights.** Rejected. It samples with replacement, so it would return duplicates or need a retry loop.
- **Deterministic top-`limit` by similarity.** Rejected. Every request would get the same few videos, and the purpose asks for a bias, not a ranking.
- **Softmax or temperature weighting.** Rejected. The issue specifies `similarity ** alpha`, and power weighting with the clamp already gives zero weight to unrelated videos.

### Gotchas, risks, limitations

- **alpha 1.0 skews only mildly.** Cosine similarities between real embeddings usually sit in a narrow positive band (roughly 0.1–0.6). With alpha 1, a 0.6 entry is only about 6 times as likely per slot as a 0.1 entry. Zero-weight entries will be rare in practice because the clamp only zeroes entries with non-positive similarity, missing embeddings or zero-norm vectors. The effect is real but gentle. A stronger bias means raising alpha (2–4), which is a config change, not a code change.
- **Very large alpha.** Small similarities can underflow to 0.0 and are then treated as zero weight. That is consistent with requirement 4. With alpha = infinity, all weights except similarities of exactly 1 become 0. Nobody would configure that, and the code does not guard against it.
- **`log(u)` safety.** `u = 1 - random.random()` is never 0, so `log` never fails. Weights are strictly positive in the keyed set, so there is no division by zero.
- **Test determinism.** Seeding `random` globally inside a test affects later code only through the module-level RNG. Tests should seed per call, or patch `popular_videos.random`. Either way they must not depend on test order.
- **Cost.** The extra work is one `log` per pool entry (at most about 5000 after caps) and one sort. That is negligible next to the existing per-entry normalisation and dot products.
- **Existing sort kept.** The `scored.sort` in the scoring step no longer affects the output. It stays because requirement 1 freezes the scoring step, and it costs little.

### Tradeoffs the operator is asked to accept

- **Behaviour changes on deploy.** For every visitor with likes on `home` and `upnext`, the popular layer changes as soon as this ships, with alpha 1.0 as the default. The only switch is the config key (set it to 0 to revert). There is no env or CLI override.
- **No epsilon term.** Popular videos with zero similarity to the likes essentially disappear from the popular layer for such visitors. Variety relies on the random, fresh and explore layers (requirement 8).
- **Duplicated sampling logic.** About ten lines of weighted sampling are duplicated rather than shared with `similar.py`, in exchange for no cross-module coupling and no changes to the up-next handler.
- **Tests pin exact sequences to a seed.** The deterministic tests are tied to `random`'s algorithm under a fixed seed. The assertions are properties with wide bounds, not exact sequences, so a change in Python's RNG would not break them.

### conflicts

none

## 2026-09-28 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="PopularVideosGenerator.get_candidates(), the final line of the likes path (line 131, `return _random_from_pool(ordered, limit)`)">
**What changes.** Line 131 becomes a branch. It reads `alpha = float(config.get("weighted_random_alpha") or 0.0)` in the style of lines 45-47, where `config` has already been normalised to `{}` at line 44. If `alpha > 0` (written that way so a NaN is disabled too) it returns `_weighted_from_pool(ordered, limit, alpha)`. Otherwise it returns `_random_from_pool(ordered, limit)` as today. The alpha read can go at the top with the other config reads or just before the draw. Either keeps the file's style, but putting it at the top keeps all config parsing in one place.

**What stays the same, verified in the file.** The three early returns at lines 72, 88 and 100 still call `_random_from_pool(pool, limit)`. Also unchanged: the pool fetch (`max(pool_size, limit)`, line 52), `apply_author_instance_caps` (56-61), the scoring loop and `entry["similarity_score"] = score` (104-113), the sort (114) and the two timing logs (116-129).

**What depends on it.**
- `engine/server/api/recommendations/mixer.py:112-123` calls `generator.get_candidates(..., config=generator_configs.get(name, {}))`, drops excluded keys, then applies `random.shuffle` when `shuffle` is set. `shuffle` is True in every profile.
- `scoring.score_candidate` (scoring.py:51,61) reads the popular entry's `similarity_score` into the unified score and writes it back, so the weighted draw also shifts the popular layer's unified scores upward.
- The only construction site is `engine/server/api/recommendations/builder.py:156-164`.

**Regression risk: low to medium.**
- The code change is small. The behaviour change is deliberate and reaches every visitor with likes on the `home` feed.
- A config value that is not numeric would raise in `float()`. Config is in-code dicts only, so this is not reachable from requests.
- The early-return paths must stay byte-for-byte unchanged (requirement 1). A reviewer should diff and confirm lines 64-100 are untouched.
</impact>
<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="new module-level helper `_weighted_from_pool(candidates, limit, alpha)`, placed next to `_random_from_pool` (lines 164-173)">
**What changes.** This is a new function. It should match `_random_from_pool`'s signature layout: a multi-line parameter list, `list[dict[str, Any]]` types and a one-line `"""Handle ..."""`-style docstring.
- It opens with the same guards as `_random_from_pool`: `limit <= 0 or not candidates` returns `[]`, and `len <= limit` returns `candidates` (requirement 6, returned as-is).
- Each weight is `float(entry.get("similarity_score") or 0.0) ** alpha`.
- Entries are split into positive-weight and zero-weight groups.
- If no weight is positive it returns `random.sample(candidates, limit)`.
- Otherwise it draws Efraimidis–Spirakis keys, `math.log(1.0 - random.random()) / weight`, keeps the top `limit`, and fills any shortfall with `random.sample(zero, limit - len(chosen))`.

**Details the implementer must get right, from the precedent `_draw_page` at `engine/server/api/handlers/similar.py:1100-1124`.**
- **Sort key.** Sort with `key=` on the float, or carry an index tiebreak as `_draw_page` does with `(key, index, row)`. Sorting bare `(float, dict)` tuples raises `TypeError` on an exact tie, because Python then compares dicts. The existing `scored.sort` at line 114 avoids this with `key=lambda item: item[0]`, and so must the new code.
- **`math` import.** The file currently imports `numpy as np`, `random` and `perf_counter`, but not `math`. `math.log` needs a new `import math` in the stdlib import block (lines 5-11), or use `np.log`. `math` matches `_draw_page`, and it keeps the RNG and log off numpy as the plan intends.
- **RNG.** It must use the module-level `random` (already imported at line 10), not `np.random`, so tests can seed it or patch `popular_videos.random`.
- **Overflow and underflow.** `similarity_score` is at most about 1.0 for normalised vectors, but float rounding can give 1.0000001. With a very large alpha that can reach `inf`, and `log(u)/inf == -0.0`, which is harmless. Small scores underflow to 0.0 and join the zero group, as the plan accepts. A negative score cannot occur, because `_max_similarity` clamps it (lines 152-161). A NaN cannot occur either: `_normalize_vector` rejects non-finite norms, but a NaN component in a vector with a finite norm could produce a NaN dot product. `best` starts at -1.0 and `nan > best` is False, so `_max_similarity` returns 0.0. The helper therefore never sees NaN from this path.

**What depends on it.** Only the new branch in `get_candidates`, and the new test file.

**Regression risk: low.** The function is new and isolated. The main hazards are the dict-comparison `TypeError` on tied keys and a forgotten `import math`, which would be a `NameError` at request time on the likes path only. Neither is caught unless the tests exercise the weighted branch.
</impact>
<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="_random_from_pool() (lines 164-173) and the module import block (lines 5-13)">
**What changes.** `_random_from_pool` itself does not change. It is still used by the three early returns and by the alpha ≤ 0 branch. The import block gains `import math` if the helper uses `math.log`. The current order is `import logging`, dataclass, typing, a blank line, then `import numpy as np` and `import random`. Put `math` with the stdlib group, or next to `random`, following the file's loose grouping.

**What depends on it.** Every return path in `get_candidates`.

**Regression risk: none** if it is left untouched. A same-named `_random_from_pool` also exists in `engine/server/api/recommendations/candidates/fresh_videos.py:149`, with the identical "sort then uniform sample" pattern at line 135. That one is out of scope and must not be edited or imported by mistake.
</impact>
<impact path="engine/server/api/server_config.py" element="RECOMMENDATION_PIPELINE['profiles']['home']['generators']['popular'] (lines 90-98)">
**What changes.** Add `"weighted_random_alpha": 1.0,` next to `pool_size` and the caps (after line 97, `"max_per_author": 2,`, or after `pool_size`). A one-line comment in the style of the file's other generator comments (lines 77-79) would help, e.g. `# similarity ** alpha draw weight when likes exist (0 disables).`

**What depends on it.**
- `mixer.generate_recommendations` → `resolve_profile_config_with_guest` (`recommendations/profile.py:23-50`), then `generator_configs.get("popular", {})`, then `PopularVideosGenerator.get_candidates(config=...)`.
- The `home` profile is chosen when the visitor has likes and the mode is `home`. The mode is always `home` for the unseeded feed (`handlers/similar.py:1006-1017`).

**Regression risk: low.**
- `tests/active/test_server_config.py:117,244` does a textual `source.count('"batch_size": 48,') == 2`, which this edit does not affect. No test reads or validates the popular generator dict, and there is no schema validation of unknown keys.
- `docs/project/issues/plan.md:73-76` warns that lanes 2a and 2d also edit `server_config.py`, so expect small merge conflicts in this file.
</impact>
<impact path="engine/server/api/server_config.py" element="RECOMMENDATION_PIPELINE['profiles']['upnext']['generators']['popular'] (lines 224-232)">
**What changes.** Add `"weighted_random_alpha": 1.0,` as in `home`.

**Discrepancy with the plan.** The plan says the popular layer changes on deploy for visitors with likes on `home` and `upnext`. In the tree, the mixer (`generate_recommendations`) is only reached from `_handle_home` (`handlers/similar.py:737`), and `_handle_home` is only called with `mode = "home"` (`similar.py:1006-1009`). Seeded requests (`mode = "upnext"`) go to `_handle_seed_with_embedding`. That path uses `resolve_profile_config_with_guest` only for the profile name and scoring, and builds its own ANN pool with `_draw_page`. `LAYER_PARAMS.md:154` confirms: "Up-next ... does not run the layers above. The `upnext` / `guest_upnext` profile supplies only its scoring weights". So the key in `upnext` has no runtime effect today. Adding it keeps the profiles symmetric and is harmless, but the operator tradeoff "behaviour changes on `home` and `upnext`" overstates the reach. The real change is `home` only.

**What depends on it.** Nothing at runtime today (grep: the only `generate_recommendations(` call is similar.py:737).

**Regression risk: none.** The key is inert. Flagged so the plan and docs do not claim an up-next behaviour change.
</impact>
<impact path="engine/server/api/server_config.py" element="guest_home (lines 176-184) and guest_upnext (lines 285-293) popular generator dicts, unchanged">
**What changes.** Nothing. Guest profiles are selected only when `has_likes` is False (`profile.py:31-40`). The popular generator then also sees no likes and takes the early return at line 72, so the key would be dead there anyway.

**Edge case.** The mixer and the generator each call `fetch_recent_likes` separately (mixer.py:69 and 88, popular_videos.py:48). If a like appears between those calls, a guest profile could reach the likes path with no key. It would then fall back to uniform, which is correct under requirement 7.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/profile.py" element="resolve_profile_config_with_guest() (lines 23-50), read only">
**What changes.** Nothing. I verified the plan's claim: it returns `profiles[name]` whole, with no merge or inheritance. So the key reaches the generator only from the profile it is written in.

**What depends on it.** `mixer.py:71` and `handlers/similar.py:773`.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/mixer.py" element="generate_recommendations() (lines 60-145), consumer, unchanged">
**What changes.** Nothing. It passes `config=generator_configs.get(name, {})` at line 117. It filters `excluded` and then `random.shuffle`s when `shuffle` is set (lines 120-123). `_soft_mix_candidates` then re-scores and re-ranks. This confirms that the helper's output order is irrelevant, so no final sort is needed.

**What depends on it.** Every home feed request.

**Regression risk: low.**
- The mixer also calls the module-level `random.shuffle`. A test that patches `popular_videos.random` does not affect it, because it is a separate module attribute. A test that calls `random.seed` globally does affect it.
- Behaviour shift: popular candidates with likes now have systematically higher `similarity_score`, so they score higher in unified scoring (`w_sim` = 1.0 in `home`). This is intended.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="PopularVideosDeps construction (lines 156-164) and fetch_popular_videos_filtered (109-113)">
**What changes.** Nothing. `PopularVideosDeps` keeps its fields, and no new dependency is injected, because alpha comes through `config` and not through deps.

**What depends on it.** The Engine's startup wiring.

**Regression risk: none,** provided the dataclass fields are not changed. The new test constructs `PopularVideosDeps` directly with all five fields, including `max_likes`.
</impact>
<impact path="engine/server/api/recommendations/filters.py" element="apply_author_instance_caps() (lines 31-96), used by the generator, unchanged; relevant to test design">
**What changes.** Nothing.

**Test-design facts.**
- `get_candidates` always passes `like_key`. So even with both caps at 0, the early return at line 47-48 does not fire, and entries are deduplicated by `like_key` (lines 74-77). The test's pool entries need distinct keys, or they collapse silently.
- Entries without `channel_id` or `instance_domain` pass uncapped.

**Regression risk: none** for production. For the test, colliding keys would quietly shrink the pool.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_draw_page() / _draw_weight() / _seeded_uniform() (lines 1088-1124), precedent only, unchanged">
**What changes.** Nothing. The plan deliberately duplicates about ten lines of this logic rather than importing it. The two differ in three ways: fill order (window order there, `random.sample` here), weight source (`_draw_weight` there, `similarity ** alpha` here), and RNG (`np.random.default_rng` or blake2b there, stdlib `random` here).

**What depends on it.** The up-next draw.

**Regression risk: none,** as long as it is not touched. `docs/project/issues/plan.md:70` lists lane 2a (issue 09) as delivered and owning `similar.py`. Do not edit it, to avoid lane conflicts.
</impact>
<impact path="tests/active/test_popular_weighted_random.py" element="new test file (name indicative)">
**What changes.** This is a new file covering the five required cases, with stub `PopularVideosDeps` and `server = SimpleNamespace(db=None, db_lock=threading.Lock())`.

**Critical correction to the plan's import setup.**
- The plan says to set up imports "the same way as the existing active tests (the `conftest.py` sys.path setup)". But `tests/active/conftest.py:37-39` only puts `client/backend` on `sys.path`, not the Engine.
- More importantly, `popular_videos.py` does `import numpy as np` at line 9. The pytest interpreter from the root `pixi.toml` has only `python` and `pytest`, with no numpy. `tests/active/test_server_config.py:73` states "pytest's own interpreter has no numpy", and `test_search_fusion.py:10-11` says "`data.search` imports numpy, which only the Engine's environment has, so each check runs in a child on the Engine's interpreter".
- So a direct `from recommendations.candidates.popular_videos import ...` in the test process will fail with `ModuleNotFoundError: numpy`.
- The test must follow the `test_search_fusion.py` / `test_similar.py` pattern instead:
  - a `textwrap.dedent` child script, run with `subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(case)])`;
  - `sys.path[:0] = [server_dir, server_dir + "/api"]` inside the child, because `popular_videos` imports `recommendations.filters`, which resolves from `engine/server/api`;
  - the child reports JSON back.
- `ENGINE_PY` can be imported from `conftest` (as `test_similar.py:109` does) or redefined as in `test_search_fusion.py:25`.
- The stub vectors must also be built inside the child with numpy.

**Other test-design gotchas found in the code.**
- **Pool size.** `get_candidates` fetches `max(pool_size, limit)` (line 52). If the test config leaves `pool_size` at 0 and the stub honours the requested count, the pool equals `limit`, and every case takes the small-pool early return inside the helper. So either set `pool_size` above `limit`, or have the stub ignore the count.
- **Embedding stub.** `fetch_embeddings_by_ids` is called twice under the lock, first with `likes` and then with `pool` (lines 76-77). The stub must return a dict keyed by `like_key` for whichever list it gets. If the liked video is also in the pool, it is not removed here, because like dedup happens in the mixer.
- **Alpha in config.** Alpha must be in the `config` passed to `get_candidates` (for example `{"weighted_random_alpha": 1.0, "pool_size": N, "max_per_author": 0, "max_per_instance": 0}`). The disabled cases (missing, `None`, 0, negative) need an assertion that tells the uniform call apart from the weighted one. For example, patch `popular_videos._weighted_from_pool` or `random.random` and assert it is not called, or compare against `random.sample` under the same seed.
- **Seeding.** Seeding happens in the child process, so it cannot leak into other tests. That fully removes the test-order concern the plan raises.
- **Timeout.** Engine interpreter start-up costs about 1 s per subprocess. Batch the cases into one child run, or a few, as `test_similar.py` does with its `cases` JSON.

**Regression risk: medium for the build.** A test written as the plan describes would error at collection or import time, not fail meaningfully.
</impact>
<impact path="tests/active/conftest.py" element="sys.path setup (lines 31-43) and ENGINE_PY constant (line 32)">
**What changes.** Nothing. The new test may import `ENGINE_PY` and `ROOT` from here. It does not provide Engine import paths. The plan's reference to "the conftest.py sys.path setup" is inaccurate: `test_random_videos.py:24-29` does its own `sys.path` insert of `engine/server` and `engine/server/api`, and that works only because `data.random_videos` does not need numpy.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_server_config.py" element="HOME_BATCH_SIZE_LITERAL count and config load (lines 116-117, 181-185, 231-247)">
**What changes.** Nothing. It loads and execs `server_config.py` and counts the literal `"batch_size": 48,` (expects 2). Adding `weighted_random_alpha` lines does not change that count or break exec.

**Regression risk: none,** unless someone reformats the `batch_size` lines while editing nearby.
</impact>
<impact path="tests/active/test_random_videos.py" element="popular pool read tests, unchanged">
**What changes.** Nothing. They exercise `data.random_videos.fetch_popular_videos` (the SQL ordering), which is upstream of the generator and untouched.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/candidates/fresh_videos.py" element="identical sort-then-uniform-sample pattern (lines 120-135, _random_from_pool at 149), out of scope">
**What changes.** Nothing. I record it because it has the same "scoring barely matters" defect and a same-named helper. It is not part of requirement 1. Do not refactor both onto a shared helper in this build.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/docs/LAYER_PARAMS.md" element="'popular Layer' section (lines 137-150)">
**What changes.** Add `- generators.popular.weighted_random_alpha` to the "Layer Params" list (after line 147), with a short gloss, for example "draw weight exponent when likes exist; 0, negative or missing disables".

Replace the Behavior text at lines 149-150. The current text reads "with likes, the pool is re-ranked by similarity; otherwise it is returned as-is (popularity with a soft freshness bonus)". "As-is" is wrong, since the code does `random.sample`. "Soft freshness bonus" is also wrong: the previous build noted that neither the pool query nor the generator applies one.

The new text should say:
- With likes, the layer draws `limit` entries without replacement, weighted by `similarity ** alpha`, and zero-weight entries only fill a shortfall.
- With alpha ≤ 0, or when all weights are zero, it draws uniformly.
- Without likes, or without usable embeddings, it takes a uniform random sample of the capped pool.
- A pool of `limit` or fewer entries is returned whole.

**Regression risk: none** (docs).
</impact>
<impact path="engine/server/api/recommendations/docs/OVERVIEW.md" element="§3 popular bullet (lines 78-83) and §4 popular pool line (line 109)">
**What changes.**
- **§3.** Lines 82-83 currently read "If likes exist, it is re-ranked by similarity. / Selection: random sample from the pool after sorting." Rewrite them: with likes, selection is a similarity-weighted draw (`similarity ** weighted_random_alpha`, without replacement); otherwise it is a uniform random sample. The plan says "around line 78". The lines that actually change are 82-83.
- **§4.** Line 109, "if likes exist, re-ranked by similarity; then caps", is slightly out of order: in the code the caps (line 56) come before scoring. Change it to something like "then caps; if likes exist, drawn weighted by similarity".

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md" element="node H3 (line 34), `Popular pool<br/>rank by similarity if likes`">
**What changes.** The plan misses this. The node describes the popular selection as ranking by similarity, which was already inaccurate (the code sampled uniformly) and becomes more so. Change it to something like `Popular pool<br/>similarity-weighted draw if likes`. It is a Mermaid label, so keep `<br/>` and avoid characters that break Mermaid parsing: `**` and parentheses inside `[...]` need care.

**Regression risk: none,** unless the edit breaks the Mermaid syntax.
</impact>
<impact path="docs/project/issues/16-popular-weighted-random.md" element="Status line and issue lifecycle">
**What changes.** On delivery, per `docs/project/triage-labels.md`: set Status to `enhancement, complete` and move the issue to `docs/project/issues/archive/`. This is normally the harvest step's job. The current Status is `enhancement, needs-triage`. The issue's "(optionally with a small epsilon)" is resolved as no epsilon (requirement 8), and a Comments note could record that.

**Regression risk: none.**
</impact>
<impact path="docs/project/roadmap.md" element="Delivered list and F3-M3 line (line 58)">
**What changes.** On delivery, add a Delivered line for issue `16`, following the format of lines 17 and 21: with likes, the home feed's popular layer is a similarity-weighted draw, `generators.popular.weighted_random_alpha` (default 1.0, 0 disables), and the plan path. Line 58 (F3-M3) lists issue `16` as related and can keep only `17`, or mark 16 delivered. This is likely a harvest-step edit, and I list it for completeness.

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/plan.md" element="Wave 2 table, lane 2c (line 72)">
**What changes.** Optionally mark lane 2c as delivered, as lane 2a is ("Delivered."). The files listed are accurate: `popular_videos.py` and `server_config.py`. The new test file and three docs are not listed, which does not matter for the lane-conflict purpose.

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/17-feed-modes.md" element="'Popular: top by likes/views' (line 18), dependency on 16 (line 23)">
**What changes.** Nothing in this build. Issue 17 depends on 16 landing first. When 17 exposes popular as a user-facing mode, whether that mode uses the likes-weighted draw is 17's decision. I record it because 16's behaviour becomes user-visible there.

**Regression risk: none.**
</impact>
<impact path="CONTEXT.md" element="glossary (Interaction signal, line 7)">
**What changes.** Nothing is required. The glossary defines no "popular layer" or "draw weight" term. Adding one is optional and not requested.

**Regression risk: none.**
</impact>


### docs_checklist

<doc path="engine/server/api/recommendations/docs/LAYER_PARAMS.md">
"popular Layer" section (lines 137-150):
- Add `generators.popular.weighted_random_alpha` to Layer Params.
- Replace lines 149-150. The "returned as-is" and "soft freshness bonus" claims are both wrong. The new text: with likes, a draw without replacement weighted by `similarity ** alpha`, where zero-weight entries only fill a shortfall. With alpha ≤ 0 or missing, or when all weights are zero, a uniform draw. Without likes or usable embeddings, a uniform random sample of the capped pool. A pool of `limit` or fewer is returned whole.
- The key has runtime effect only in the `home` profile, because the mixer never runs for `upnext` (line 154 already says so).
</doc>
<doc path="engine/server/api/recommendations/docs/OVERVIEW.md">
- §3 popular bullet, lines 82-83: "re-ranked by similarity" and "random sample from the pool after sorting" become a similarity-weighted draw with likes and a uniform sample otherwise.
- §4 line 109, popular pool: say the caps come first, then a draw weighted by similarity when likes exist.
</doc>
<doc path="engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md">
Line 34: change the node label `H3[Popular pool<br/>rank by similarity if likes]` to something like `similarity-weighted draw if likes`, keeping the Mermaid syntax valid. The plan does not list this doc.
</doc>
<doc path="docs/project/issues/16-popular-weighted-random.md">
On delivery, set Status to `enhancement, complete` and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`. Note that no epsilon term was chosen.
</doc>
<doc path="docs/project/roadmap.md">
On delivery, add a Delivered line for issue `16` (similarity-weighted popular draw on the home feed, `generators.popular.weighted_random_alpha`, default 1.0, 0 disables) and update the F3-M3 "Related" list at line 58.
</doc>
<doc path="docs/project/issues/plan.md">
Optionally mark lane 2c (line 72) as delivered, as lane 2a is.
</doc>

### highest_risk

tests/active/test_popular_weighted_random.py (new): the plan imports `popular_videos` directly via "the conftest.py sys.path setup", but that module imports numpy at line 9, and the pytest interpreter has no numpy (`test_server_config.py:73`, `test_search_fusion.py:10-11`). The test has to run its cases in a child on `ENGINE_PY`. Also, `pool_size` of 0 makes the pool equal `limit`, so the weighted path would never run.
engine/server/api/recommendations/candidates/popular_videos.py `_weighted_from_pool` (new): sorting `(key, dict)` tuples without a `key=` or an index tiebreak raises `TypeError` on a tie, and `math` is not yet imported. Either would break the likes path of every home feed at request time, and only a test that exercises the weighted branch would catch it.
engine/server/api/server_config.py `upnext` profile: the plan's claim that behaviour changes on `upnext` is wrong. The mixer is only reached with mode `home` (`handlers/similar.py:1006-1017`), so the `upnext` key is inert. The operator tradeoff and any doc text saying up-next changes would be inaccurate.

## 2026-09-28 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked every inventory entry against its file. All of them hold. The plan will work as designed, and the change reaches less than the plan says. Only the home feed changes at runtime, for visitors with likes. The key added to `upnext` has no effect. The inventory already records the two real problems: the plan's test-import setup, which would fail without numpy, and the plan's claim that up-next behaviour changes. I found nothing new. The loop has converged.
<question id="1">
Yes. `popular_videos.py:130-131` is the single final draw of the likes path. The other three returns (72, 88, 100) and the whole scoring block (102-129) can stay as they are. `similarity_score` is already clamped to 0 or more by `_max_similarity` (lines 156-161). `float(config.get(...) or 0.0)` matches lines 45-47, and a NaN alpha fails `> 0`. `ordered` comes from `scored`, which is already sorted with `key=` at line 114, so the ES helper can take it directly. The precedent `_draw_page` (`similar.py:1100-1124`) shows the same algorithm running in this codebase, including the `(key, index, row)` tiebreak the new code needs. The profile path is confirmed: `profile.py:42-43` returns `profiles[mode]` whole, and `mixer.py:117` passes `generator_configs.get(name, {})`. So the key reaches the generator only in `home`, and only when `has_likes` is true.
</question>
<question id="2">
- **Visible change.** Home-feed popular candidates for visitors with likes lean toward videos similar to those likes. Their `similarity_score` rises on average, and `score_candidate` (scoring.py:51,61) reuses it with `w_sim` 1.0 in `home`. The popular layer therefore also ranks slightly higher in the unified mix. This is intended.
- **Up-next.** Nothing changes. `generate_recommendations` is called only from `_handle_home` (similar.py:737). Seeded requests go to `_handle_seed_with_embedding`, which uses the profile only to get scoring weights.
- **Guests.** Nothing changes. Guest profiles are chosen only without likes (profile.py:31-40), and the generator then takes the no-likes early return.
- **Cost.** One `log` and one sort per pool entry. This is negligible.
- **Tests.** The new test must run in an Engine-interpreter child process. `popular_videos.py:9` imports numpy, and pytest's interpreter has none (test_server_config.py:73, test_search_fusion.py:10-11).
</question>
<question id="3">
- **Import.** Add `import math`. The file has only `numpy`, `random` and `perf_counter` (lines 9-11).
- **Sort key.** The ES sort needs a `key=` or an index tiebreak so exact ties never compare dicts.
- **Early returns.** Leave the three early returns and `_random_from_pool` untouched.
- **Test file.** Build it on the `test_search_fusion.py` child pattern: `ENGINE_PY` and `sys.path[:0] = [server, server/api]`. Construct the stub vectors inside the child. Give pool entries distinct `like_key`s, because `apply_author_instance_caps` dedups by `like_key` even with caps at 0 (filters.py:47,74-77). Make the pool larger than `limit` via `pool_size`, or the helper's small-pool return hides the weighted branch.
- **Docs.** Update `LAYER_PARAMS.md:149-150`, `OVERVIEW.md:82-83` and 109, and `PIPELINE_DIAGRAM.md:34`. The last one is not in the plan's doc list, but the inventory carries it.
- **Nothing else.** No change is needed in the mixer, builder, profile resolution, `fresh_videos.py` or `similar.py`.
</question>
<question id="4">
- **Before.** On the home feed with likes, the popular layer took a uniform `random.sample` of the capped pool. The similarity sort had no effect on which videos were picked.
- **After (alpha > 0).** It draws without replacement with weight `similarity ** alpha`. Zero-similarity videos appear only when there are too few positive-weight ones to fill `limit`.
- **Unchanged.** The layer is still uniform when there are no likes, no usable embeddings, alpha ≤ 0 or missing, or every weight is zero. A pool of `limit` or fewer is still returned whole. Pool contents, caps and output size are the same.
- **Order.** Output order still has no effect, because the mixer shuffles (mixer.py:122-123) and then re-ranks by unified score.
- **Not altered.** Up-next and guest feeds.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Correct the operator tradeoff wording from "`home` and `upnext`" to "`home` only". The upnext key stays in for symmetry, and the docs should not claim an up-next change (LAYER_PARAMS.md:154 already says up-next skips the layers). Cost: one sentence. Nothing in the design changes, so I have not raised this as a conflict.
2. Tell the test-writing step to use the Engine-interpreter child pattern (`test_search_fusion.py:23-60`) instead of the "conftest sys.path setup". Batch all five cases into one child run. Cost: a slightly more elaborate test file, and about 1 s of interpreter start-up per child. Without this, the test fails at import with `ModuleNotFoundError: numpy` and gates nothing.
3. Include `PIPELINE_DIAGRAM.md:34` (node H3) in the doc edits. Keep the Mermaid label free of `**` and parentheses, e.g. `Popular pool<br/>similarity-weighted draw if likes`. Cost: one line.
4. Have the helper's tests reach the weighted branch: `pool_size` greater than `limit`, distinct keys, and at least one test with alpha > 0 where the pool is larger than `limit`. Otherwise a missing `import math` or a dict-comparison tie error would only surface in production. Cost: none beyond test design.
5. Informational, no action: `docs/project/issues/plan.md:111` lists lane 6b (issue 29, recommendations overview doc) as depending on 16. This build's `OVERVIEW.md` edits are input to that later rewrite. Keep them short and accurate. Expect `server_config.py` merge conflicts with lanes 2a and 2d, as the inventory notes.

## 2026-09-28 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft: similarity-weighted draw in the popular layer (issue 16)

Note on the brief: the "ladder the draft is written against" section came through as the literal placeholder `{rat_tail_ladder}`, so no ladder was given. This draft is checked against the plan, the eight requirements and the settled impact inventory. It converged on the second pass (see "Check against plan and requirements").

### Module map

| File | Change |
|---|---|
| `engine/server/api/recommendations/candidates/popular_videos.py` | Adds `import math`. Adds one config read at the top of `get_candidates`. Line 131 becomes a two-way branch. Adds a new helper `_weighted_from_pool` after `_random_from_pool`. |
| `engine/server/api/server_config.py` | Adds `"weighted_random_alpha": 1.0` to `home` and `upnext` → `generators.popular`. Guest profiles are untouched. |
| `tests/active/test_popular_weighted_random.py` | New file. All cases run in one Engine-interpreter child and are seeded per trial. |
| `engine/server/api/recommendations/docs/LAYER_PARAMS.md` | Adds the key to the list and replaces the Behavior text. |
| `engine/server/api/recommendations/docs/OVERVIEW.md` | Rewrites §3 lines 82-83 and §4 line 109. |
| `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` | Changes the H3 node label (line 34). |

The issue, roadmap and plan.md lifecycle edits belong to the harvest step, so they are not drafted here.

### `popular_videos.py`

**Imports (lines 5-11).** `math` goes into the stdlib group. The rest of the file's loose grouping stays as it is:

```python
import logging
import math
from dataclasses import dataclass
from typing import Any, Callable
```

**Config read.** It goes with the other reads (after line 47), in the file's style:

```python
        max_per_author = int(config.get("max_per_author") or 0)
        weighted_random_alpha = float(config.get("weighted_random_alpha") or 0.0)
```

A missing key or `None` goes through `or 0.0` and becomes 0.0. A 0 or a negative value becomes itself. A NaN stays NaN and fails the `> 0` test below. In each of those cases the draw is disabled.

**The last line of the likes path (line 131)** becomes:

```python
        ordered = [item[1] for item in scored]
        if weighted_random_alpha > 0:
            return _weighted_from_pool(ordered, limit, weighted_random_alpha)
        return _random_from_pool(ordered, limit)
```

Lines 42-130 stay byte-for-byte the same except for the one added read line. That covers the three early returns (72, 88, 100), the fetch, the caps, the scoring, `entry["similarity_score"] = score`, the sort (114) and the timing logs.

**New helper**, placed directly after `_random_from_pool`, with the same signature layout:

```python
def _weighted_from_pool(
    candidates: list[dict[str, Any]],
    limit: int,
    alpha: float,
) -> list[dict[str, Any]]:
    """Handle weighted from pool: draw without replacement by similarity_score ** alpha (Efraimidis-Spirakis); zero weights only fill a shortfall, uniformly."""
    if limit <= 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    keyed: list[tuple[float, dict[str, Any]]] = []
    unweighted: list[dict[str, Any]] = []
    for entry in candidates:
        weight = float(entry.get("similarity_score") or 0.0) ** alpha
        if not weight > 0:
            unweighted.append(entry)
            continue
        keyed.append((math.log(1.0 - random.random()) / weight, entry))
    if not keyed:
        return random.sample(candidates, limit)
    keyed.sort(key=lambda item: item[0], reverse=True)
    chosen = [item[1] for item in keyed[:limit]]
    if len(chosen) < limit:
        chosen.extend(random.sample(unweighted, limit - len(chosen)))
    return chosen
```

**What the helper guarantees:**
- **Output size and duplicates.** If the input has more than `limit` entries, the output has exactly `limit` entries and no entry appears twice. Each input entry sits in exactly one of `keyed` or `unweighted`, and `random.sample` draws without replacement. A shortfall means `len(keyed) < limit`, so `len(unweighted) = len(candidates) - len(keyed) > limit - len(keyed)` and the fill sample is always feasible.
- **Small pool.** If the input has `limit` or fewer entries, all of them come back as-is, the same as `_random_from_pool` (requirement 6).
- **All zero.** If no weight is positive, the result is exactly `random.sample(candidates, limit)`. No `random.random()` call happens before it, so the RNG stream matches today's uniform call under the same seed (requirement 5).
- **Where zero-weight entries appear.** They appear only when `len(keyed) < limit`, and then they are drawn uniformly (requirement 4).
- **Key safety.** `u = 1 - random.random()` is in (0, 1], so `log` never fails. The weight is strictly positive, so there is no division by zero. A weight of `inf` gives a key of `-0.0`, which is harmless.
- **Sort.** The sort uses `key=` on the float only, so tied keys never compare dicts (the `TypeError` hazard noted in the impact inventory).
- **NaN.** `not weight > 0` sends a NaN weight to the zero group. `_max_similarity` should already make NaN unreachable, so this costs nothing.
- **Order.** The output is returned without a final sort. The mixer shuffles it and then re-sorts by unified score, so the order is irrelevant.
- **RNG.** The helper uses only the module-level `random` (already imported), so a test can seed it or patch it.

**Decisions:**
- This is a local copy of the `_draw_page` idea, not an import of it. The weight source, the fill policy (uniform here, window order there), the RNG and the output order all differ.
- The copy is a deliberate duplication of about fifteen lines. Its ceiling is two call sites. The upgrade path, when a third caller appears, is one helper that takes a weight function and a fill policy.
- `similar.py` and `fresh_videos.py` are not touched.

### `server_config.py`

`home` → `generators.popular` (lines 90-98) and `upnext` → `generators.popular` (lines 224-232) get the same two lines after `"max_per_author": 2,`:

```python
                    "max_per_author": 2,
                    # similarity ** alpha draw weight when likes exist (0 disables).
                    "weighted_random_alpha": 1.0,
                },
```

- `guest_home` and `guest_upnext` stay unchanged.
- The `"batch_size": 48,` literal count checked in `test_server_config.py` is unaffected.

**Flag, per the settled impact inventory.** The plan's tradeoff says behaviour changes "on `home` and `upnext`". In the tree, the mixer runs only for `home`, so the `upnext` key is inert today. It is added only to keep the two profiles symmetric. The docs below say the key takes effect in `home` only. The operator-facing tradeoff should read "changes on deploy for visitors with likes on the home feed".

### `tests/active/test_popular_weighted_random.py`

**Why the plan's import setup changes.** `popular_videos` imports numpy. The pytest interpreter does not have numpy, and `conftest.py` puts only `client/backend` on the path. So this file follows the `test_search_fusion.py` pattern instead: a `textwrap.dedent` child runs on `ENGINE_PY` with `sys.path[:0] = [server, server + "/api"]` and reports back as JSON.

**One subprocess.** All cases run in one child from a module-scoped fixture. That is one Engine interpreter start-up of about 1 s.

**Determinism.** Every trial reseeds `random` inside the child with a string seed (`random.seed(f"{name}:{trial}")`). String seeds are deterministic across processes. Nothing leaks into other tests, and test order does not matter.

**Stubs:**
- The pool is a JSON object mapping id to nominal similarity. `None` means the entry has no embedding.
- Each vector is `[s, sqrt(1 - s²)]` against a like vector `[1, 0]`, so the cosine equals `s`. A negative `s` is clamped to 0 by `_max_similarity`.
- `fetch_popular_videos` ignores the requested count and always returns the whole fixed pool. This avoids the trap where `max(pool_size, limit)` makes the pool equal `limit`.
- Ids are distinct, so the `like_key` dedup inside the caps does not collapse the pool.
- Both caps are 0.
- The disabled cases replace `popular_videos._weighted_from_pool` with a function that raises. A wrong branch then crashes the child, and the fixture's return-code assert fails.
- The uniform cases also recompute `random.sample(ordered_ids, limit)` under the same seed. `ordered_ids` is the pool sorted by clamped nominal similarity, descending, and the sort is stable, like the generator's `scored.sort`. The test asserts equality with that sample. This works because `random.sample` picks the same indices whatever the element type is.

```python
"""Similarity-weighted draw in the popular layer.

- With likes and `weighted_random_alpha` > 0, the layer draws `limit` candidates without replacement, weighted by `similarity_score ** alpha`: closer videos come out clearly more often, none twice.
- Zero-weight candidates only fill what the positive ones cannot; if every weight is zero the draw is today's uniform sample.
- A missing, None, zero, negative or NaN alpha keeps today's uniform `random.sample`.
- A pool of `limit` or fewer comes back whole.

`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.
"""
from __future__ import annotations

import json
import subprocess
import textwrap

import pytest

from conftest import ENGINE_PY, ROOT

SERVER_DIR = ROOT / "engine" / "server"
LIMIT = 5

_CHILD = textwrap.dedent(
    """
    import json, math, random, sys, threading
    from types import SimpleNamespace
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    import numpy as np
    from recommendations.candidates import popular_videos
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator

    WEIGHTED = popular_videos._weighted_from_pool
    SERVER = SimpleNamespace(db=None, db_lock=threading.Lock())

    def vector(sim):
        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)

    def generator(pool):
        table = {"like": np.array([1.0, 0.0], dtype=np.float32)}
        table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})
        return PopularVideosGenerator(PopularVideosDeps(
            fetch_popular_videos=lambda db, count: [{"video_id": vid} for vid in pool],
            fetch_recent_likes=lambda user_id, count: [{"video_id": "like"}],
            fetch_embeddings_by_ids=lambda db, rows: {r["video_id"]: table[r["video_id"]] for r in rows if r["video_id"] in table},
            like_key=lambda row: row["video_id"],
            max_likes=10,
        ))

    def refuse(*args, **kwargs):
        raise AssertionError("weighted draw ran while disabled")

    out = {}
    for case in json.loads(sys.argv[2]):
        pool, limit = case["pool"], case["limit"]
        config = {"pool_size": len(pool), "max_per_author": 0, "max_per_instance": 0}
        if "alpha" in case:
            config["weighted_random_alpha"] = float("nan") if case["alpha"] == "nan" else case["alpha"]
        popular_videos._weighted_from_pool = refuse if case.get("disabled") else WEIGHTED
        ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)
        gen = generator(pool)
        draws, expected = [], []
        for trial in range(case["trials"]):
            random.seed(f"{case['name']}:{trial}")
            draws.append([row["video_id"] for row in gen.get_candidates(SERVER, "user", limit, config=config)])
            if case.get("uniform"):
                random.seed(f"{case['name']}:{trial}")
                expected.append(random.sample(ordered, limit))
        out[case["name"]] = {"draws": draws, "expected": expected}
    popular_videos._weighted_from_pool = WEIGHTED
    print(json.dumps(out))
    """
)


def _pool(**groups: tuple[int, float | None]) -> dict[str, float | None]:
    return {f"{prefix}{i}": sim for prefix, (count, sim) in groups.items() for i in range(count)}


HI_LO = _pool(hi=(10, 0.9), lo=(10, 0.1))
DISABLED = {"disabled_missing": {}, "disabled_none": {"alpha": None}, "disabled_zero": {"alpha": 0}, "disabled_negative": {"alpha": -1.0}, "disabled_nan": {"alpha": "nan"}}

CASES = [
    {"name": "skew", "pool": HI_LO, "alpha": 1.0, "limit": LIMIT, "trials": 400},
    {"name": "zero_fill", "pool": {**_pool(p=(3, 0.5), z=(5, 0.0)), "neg0": -0.5, "none0": None}, "alpha": 1.0, "limit": LIMIT, "trials": 100},
    {"name": "zero_unused", "pool": _pool(p=(6, 0.5), z=(10, 0.0)), "alpha": 1.0, "limit": LIMIT, "trials": 200},
    {"name": "all_zero", "pool": {**_pool(z=(10, 0.0)), "neg0": -0.3, "none0": None}, "alpha": 1.0, "limit": LIMIT, "trials": 50, "uniform": True},
    *({"name": name, "pool": HI_LO, **extra, "limit": LIMIT, "trials": 50, "uniform": True, "disabled": True} for name, extra in DISABLED.items()),
    {"name": "small_equal", "pool": {"a": 0.9, "b": 0.5, "c": 0.0, "d": None, "e": 0.2}, "alpha": 1.0, "limit": LIMIT, "trials": 3},
    {"name": "small_under", "pool": {"a": 0.9, "b": 0.0, "c": 0.4}, "alpha": 1.0, "limit": LIMIT, "trials": 3},
]


@pytest.fixture(scope="module")
def draws() -> dict[str, dict[str, list]]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(CASES)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _assert_full_and_distinct(results: list[list[str]]) -> None:
    for draw in results:
        assert len(draw) == LIMIT and len(set(draw)) == LIMIT, draw


def test_closer_candidates_are_drawn_clearly_more_often_and_never_twice(draws):
    results = draws["skew"]["draws"]
    _assert_full_and_distinct(results)
    hi = sum(vid.startswith("hi") for draw in results for vid in draw)
    lo = sum(vid.startswith("lo") for draw in results for vid in draw)
    assert hi >= 3 * lo, (hi, lo)  # expected ~9:1 per slot at alpha 1; 3:1 cannot flake under any seed


def test_zero_weight_candidates_only_fill_what_positive_ones_cannot(draws):
    filled = draws["zero_fill"]["draws"]
    _assert_full_and_distinct(filled)
    fill_ids: set[str] = set()
    for draw in filled:
        assert {"p0", "p1", "p2"} <= set(draw), draw  # every positive-weight candidate is taken first
        fill_ids |= set(draw) - {"p0", "p1", "p2"}
    assert fill_ids == {"z0", "z1", "z2", "z3", "z4", "neg0", "none0"}  # the fill spreads over every zero-weight candidate
    unused = draws["zero_unused"]["draws"]
    _assert_full_and_distinct(unused)
    assert all(vid.startswith("p") for draw in unused for vid in draw)  # enough positives: zero weights never appear


def test_all_zero_weights_fall_back_to_the_uniform_sample(draws):
    case = draws["all_zero"]
    _assert_full_and_distinct(case["draws"])
    assert case["draws"] == case["expected"]


@pytest.mark.parametrize("name", list(DISABLED))
def test_a_missing_none_zero_negative_or_nan_alpha_keeps_the_uniform_sample(draws, name):
    case = draws[name]  # the child's weighted helper raised if called, so reaching here means the uniform branch ran
    _assert_full_and_distinct(case["draws"])
    assert case["draws"] == case["expected"]


@pytest.mark.parametrize("name", ["small_equal", "small_under"])
def test_a_pool_of_limit_or_fewer_comes_back_whole(draws, name):
    pool = next(case["pool"] for case in CASES if case["name"] == name)
    for draw in draws[name]["draws"]:
        assert sorted(draw) == sorted(pool)
```

**Why each assertion holds, and that none can flake:**
- **skew.** At alpha 1 each hi entry carries 9 times the weight of a lo entry, so nearly every slot goes to hi. The 3:1 bound sits far below that, and a fixed seed makes the run reproducible anyway.
- **zero_fill.** There are 3 positive entries for `limit` 5, so every draw takes all three plus 2 of the 7 zero-weight entries (0.0, negative clamped to 0, missing embedding). The chance that 100 trials miss one particular zero entry is about (15/21)^100 ≈ 1e-15.
- **zero_unused.** There are 6 positive entries for `limit` 5, so the zero group is never reached.
- **all_zero.** It asserts equality with `random.sample(ordered, 5)`, because the helper consumes no RNG before that sample. All scores are 0.0, so the generator's stable reverse sort leaves pool order unchanged, and `ordered` in the child reproduces it.
- **Disabled.** The uniform branch is `_random_from_pool(ordered, limit)`, which is `random.sample(ordered, 5)`. The two groups have distinct scores, and within a group the dots are identical, so the stable sort order matches `ordered`.
- **Small pool.** A pool of `limit` or fewer entries is returned whole.

### Docs

**`LAYER_PARAMS.md`.** Add after line 147:

```markdown
- `generators.popular.weighted_random_alpha` — draw-weight exponent when likes exist; 0, negative or missing disables (uniform draw). Set in `home` (1.0); the `upnext` value is inert because the mixer does not run for up-next.
```

Replace lines 149-150 with:

```markdown
Behavior: the pool is capped first. With likes and usable embeddings, each entry's `similarity_score` is its best cosine to the liked videos (clamped at 0), and the layer draws `limit` entries without replacement weighted by `similarity_score ** weighted_random_alpha`; zero-weight entries only fill slots the positive-weight ones cannot, uniformly at random. With alpha ≤ 0 or missing, or when every weight is zero, the draw is uniform. Without likes or usable embeddings, the layer takes a uniform random sample of the capped pool. A pool of `limit` or fewer entries is returned whole.
```

**`OVERVIEW.md` §3, lines 82-83.** Replace with:

```markdown
  If likes exist, each entry gets `similarity_score` (best cosine to the likes).
  Selection: with likes, a draw without replacement weighted by `similarity_score ** weighted_random_alpha` (zero weights only fill a shortfall); otherwise a uniform random sample from the pool.
```

**`OVERVIEW.md` §4, line 109.** Replace with:

```markdown
- **popular pool**: top by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then likes and views; then caps; if likes exist, drawn weighted by similarity to the likes.
```

**`PIPELINE_DIAGRAM.md`, line 34.** Replace with the label below. It contains no parentheses or `**`, so the Mermaid syntax stays valid:

```
    G3 --> H3[Popular pool<br/>similarity-weighted draw if likes]
```

### Check against plan and requirements

**Pass 1.** Two problems found and fixed:
- The plan's test import path (`conftest` sys.path) cannot import numpy. The test was moved to an Engine-interpreter child, as the impact inventory directs.
- The pool stub honoured `count`, which would have forced every case into the small-pool early return. The stub was changed to always return the fixed pool.

**Pass 2.** Every item checks out:

| Requirement | How it is met |
|---|---|
| R1: only the final draw changes | Only line 131 changes, plus one config read. The early returns are untouched. |
| R2: weight is `similarity_score ** alpha` | The helper computes exactly that. |
| R3: weighted draw without replacement, higher weight more likely | Efraimidis–Spirakis with the top `limit` keys. Covered by the skew test. |
| R4: zero weights only fill a shortfall, uniformly | Uniform `random.sample` fill. Covered by the zero_fill and zero_unused tests. |
| R5: all-zero fallback | Exactly `random.sample(candidates, limit)`. The test asserts equality with it. |
| R6: small pool | The guard returns the pool whole, as today. Covered by the small-pool tests. |
| R7: disabled | Missing, `None`, 0, negative and NaN all reach `_random_from_pool` unchanged. Tested with the weighted helper patched to refuse. |
| R8: no epsilon term | None is added. |
| Config | The key is in `home` and `upnext`, and absent from guest profiles. |
| Docs | All three docs edits above. |
| Suite | The existing `test_server_config` count is unaffected. The new tests need only `ENGINE_PY`, which the existing active tests already require. |

**Still open for the operator** (a tradeoff wording issue, not a defect): the plan says behaviour changes on `home` and `upnext`, but the real change is `home` only.

## 2026-09-28 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Similarity-weighted popular draw [code]

**Files touched.** engine/server/api/recommendations/candidates/popular_videos.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_popular_weighted_random.py (NEW)

**Checkpoint.** Seam: the public `PopularVideosGenerator.get_candidates(server, user_id, limit, config=...)`. It is driven with stub `PopularVideosDeps`: a fixed pool that ignores `count`, one like `[1, 0]`, and 2-D vectors `[s, sqrt(1-s²)]` so each cosine is exactly `s`. The caps are 0 and the server is a `SimpleNamespace(db=None, db_lock=threading.Lock())`. Harness: `tests/active/test_popular_weighted_random.py` runs every case in one Engine-interpreter child (`ENGINE_PY -c _CHILD SERVER_DIR CASES_JSON`, `sys.path[:0] = [server, server + "/api"]`), which reseeds `random` per trial with a string seed and reports JSON. This follows the existing ENGINE_PY child precedent in `test_search_fusion.py` and `test_internal_client_reads.py`; that route is needed because the pytest interpreter lacks numpy. Asserts for clause_1: skew (10 hi at 0.9 vs 10 lo at 0.1, alpha 1, 400 trials): every draw has `limit` distinct ids, and hi hits ≥ 3 × lo hits. zero_fill (3 positive, 7 zero-weight including negative and missing-embedding, limit 5): all 3 positives are in every draw, and across trials the fill covers every zero-weight id. zero_unused (6 positive, 10 zero): no zero-weight id ever appears. Asserts for clause_2: all_zero and the five disabled configs (key missing, None, 0, -1.0, NaN) each equal `random.sample(ordered, limit)` recomputed under the same seed. In the disabled cases `popular_videos._weighted_from_pool` is replaced by a function that raises, so taking the wrong branch fails the fixture's return-code assert. Regression guard: pools of exactly `limit` and fewer than `limit` come back whole.

**Intent.** `PopularVideosGenerator.get_candidates` in `popular_videos.py` ends its likes path in a new `_weighted_from_pool` draw that favours candidates closer to the likes whenever `weighted_random_alpha` is positive (1.0 in the `home` and `upnext` profiles), and ends it in today's uniform `_random_from_pool` sample otherwise.

- C1 - With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`.
- C2 - With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed.

**Outcome.** _pending_


Needs coordination: none

Rationale: There is one phase because the change is a single behaviour at a single call site. It is one branch on line 131 plus one helper of about 20 lines, and one test file drives both the weighted path and the uniform guard through the same `get_candidates` seam. Splitting the weighted draw from the disabled/uniform guard would give a phase whose checkpoint is already green before it lands, since today's code already draws uniformly. So the Intent cuts into two clauses: the weighted draw's properties, and exact equality with the uniform sample when disabled or all-zero. The small-pool case is kept in the checkpoint as a regression guard, not as a clause, because it is already true today (R6). Two items get no clause, on purpose. First, the `weighted_random_alpha: 1.0` literal in `server_config.py` is configuration data with no behaviour of its own. The settled draft's test does not read it, so the only checks are the green full suite (`test_server_config` still loads and counts the profiles) and review. The operator saw this and approved it. Second, the LAYER_PARAMS.md, OVERVIEW.md and PIPELINE_DIAGRAM.md edits are human-facing documentation, so they are not a phase; Step 9 writes them from what was delivered. Flags: the brief's {principles}, {shape_ladder-ladder} and {tdd_seams} slots arrived as unfilled placeholders, so the seam comes from the tree's existing ENGINE_PY child-process tests. As the draft notes, the mixer runs only for `home`, so the behaviour change on deploy reaches the home feed only, and the `upnext` key has no effect today. The operator was told about both.

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`PopularVideosGenerator.get_candidates` in `popular_videos.py` ends its likes path in a new `_weighted_from_pool` draw that favours candidates closer to the likes whenever `weighted_random_alpha` is positive (1.0 in the `home` and `upnext` profiles), and ends it in today's uniform `_random_from_pool` sample otherwise.

- C1 - With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`.
- C2 - With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed.

must_prove:
- C1 - With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`.
- C2 - With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed.

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - self-check (audit round 1, send-back 0)

`tests/tmp/test_16_popular_weighted_random_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_16_popular_weighted_random_phase1.py:111 — `hi >= SKEW[name][1] * lo`, run on the lo-first 10×0.9 / 10×0.1 pool over 400 seeded trials: at least 3:1 at alpha 1.0 (`skew`) and at least 2:1 at alpha 0.5 (`skew_half`). Line 107 (`_assert_full_and_distinct`) goes with it and checks that every draw has `limit` distinct ids. Line 112 (`lo > 0`) checks the result is a draw and not a top-`limit` cut. - expected: A reference Efraimidis–Spirakis draw, run in probe `tests/tmp/probe_16_reference_draw.py` under the same seeds, gave hi:lo 1773:227 at alpha 1.0 and 1468:532 at alpha 0.5. Both clear their bounds, and lo is above 0. Against the code as it stands, the run showed (974, 1026) for `skew` and (1042, 958) for `skew_half`, so both fail at line 111. - excludes: Today's uniform `random.sample(ordered, limit)` at line 131 reads 974:1026 and 1042:958, which is red for both. An alpha read in the file's `int(config.get(...) or 0)` style turns 0.5 into 0, so that path is uniform: `skew_half` reads about 1:1 and is red, while `skew` stays green. A deterministic top-`limit` by similarity gives lo == 0, which is red at line 112. A with-replacement `random.choices` draw repeats ids, which is red at line 101 through line 107.
- C1 - tests/tmp/test_16_popular_weighted_random_phase1.py:121 and :123 — in `zero_fill` (3 candidates at 0.5; 7 zero-weight candidates at 0.0, −0.5 or with no embedding; limit 5; 100 trials) every draw contains p0, p1 and p2. Across the trials the fill covers all 7 zero-weight ids. Line 126: in `zero_unused` (6 at 0.5, 10 at 0.0) no id without the `p` prefix ever appears. Lines 117 and 125 check `limit` distinct ids per draw. - expected: Under the reference draw in the probe, every positive appears in every draw, and the union of the fills is {neg0, none0, z0..z4} (seen: `zero_fill union ['neg0', 'none0', 'p0', 'p1', 'p2', 'z0', 'z1', 'z2', 'z3', 'z4']`). Against the current code, the run failed at line 121 on the draw ['z4', 'z1', 'z3', 'z0', 'neg0'], where p0, p1 and p2 are all missing. - excludes: A uniform sample drops positives from draws, which is red at line 121 (the draw above) and would be red at line 126. A zero-weight fill taken in window order, as `_draw_page` does, always fills with z0 and z1, so line 123 sees {z0, z1} and is red. A weighted draw that gives zero weights a small nonzero weight sometimes lets a zero-weight id displace a positive, which is red at line 121 or line 126.
- C2 - tests/tmp/test_16_popular_weighted_random_phase1.py:139 — for alpha missing, None, 0, −1.0 and NaN on the lo-first pool, `case["draws"] == case["expected"]`. The expected value is `random.sample(ordered, 5)` under the same per-trial seed over 50 trials. `ordered` is the pool sorted by clamped similarity (hi first), not the pool's own lo-first order. Line 138 checks `limit` distinct ids. - expected: Equal for all five, and green against the current code, as the run showed (5 of the 8 passing tests). This clause guards existing behaviour: it says the disabled path stays exactly as it is today. - excludes: A disabled alpha that still goes to a weighted helper uses up `random.random()` before sampling, so the draws differ from `expected`. The same happens with an alpha read that turns NaN into "enabled" (for example `if alpha != 0`). A disabled path that samples the unsorted `pool` instead of `ordered` also differs: the probe found 50 of 50 seeded samples differ (`ordered head ['hi0', 'hi1', 'hi2'] pool head ['lo0', 'lo1', 'lo2']`). An `int(nan)` read raises in the child and fails the fixture at line 95.
- C2 - tests/tmp/test_16_popular_weighted_random_phase1.py:132 — with alpha 1.0 and every weight 0 (0.0, −0.3, no embedding), `case["draws"] == case["expected"]`, the same-seed `random.sample(ordered, 5)`, over 50 trials. Line 131 checks `limit` distinct ids. - expected: Equal, and green against the current code, as the run showed. It is a regression guard for the all-zero fallback. - excludes: A helper that calls `random.random()` for every entry before noticing that no weight is positive shifts the stream, so the draws differ from `expected`. So does one that treats zero weights as tiny positive weights and runs the keyed draw. A helper that returns `[]` or only the (empty) positive group when all weights are zero is red at line 101 through line 131.

<assertions>
tests/tmp/test_16_popular_weighted_random_phase1.py:108 — the Engine child exits 0. In the five disabled cases `popular_videos._weighted_from_pool` is replaced by a function that raises, so a wrong branch fails here with the case name in stderr. — C2
tests/tmp/test_16_popular_weighted_random_phase1.py:115 (via `_assert_full_and_distinct`, called at 121, 129, 137) — every skew, zero_fill and zero_unused draw has exactly `limit` (5) ids, all distinct. — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:123 — skew (10 at 0.9 vs 10 at 0.1, alpha 1.0, 400 trials): hi hits ≥ 3 × lo hits. — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:124 — skew: lo hits > 0, so the result is a random draw and not a deterministic top-`limit` pick. — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:133 — zero_fill (3 at 0.5, plus 7 zero-weight: five at 0.0, one negative, one with no embedding; limit 5): all 3 positives are in every one of 100 draws. — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:135 — zero_fill: across the trials, the fill ids equal exactly the set of all 7 zero-weight ids (uniform fill, not pool order). — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:138 — zero_unused (6 at 0.5, 10 at 0.0, 200 trials): no zero-weight id ever appears. — C1
tests/tmp/test_16_popular_weighted_random_phase1.py:143-144 — all_zero (every weight 0, with alpha 1.0): each draw has `limit` distinct ids and equals `random.sample(ordered, limit)`, recomputed in the child under the same per-trial string seed. — C2
tests/tmp/test_16_popular_weighted_random_phase1.py:150-151 — the five disabled configs (key missing, None, 0, -1.0, NaN) over the hi/lo pool: each draw has `limit` distinct ids and equals `random.sample(ordered, limit)` under the same seed. `ordered` is the nominal similarity clamped at 0, sorted stable and descending. — C2
tests/tmp/test_16_popular_weighted_random_phase1.py:159 — regression guard: pools of exactly `limit` (5) and fewer (3), with alpha 1.0, come back whole in every trial. — regression guard (no clause)
</assertions>

<probes>
1. `ValidateTests tests/tmp/probe_16_popular_child.py -s` — the Engine child, with the stub deps, run against today's `popular_videos.py`. It printed `has_weighted False`, so `_weighted_from_pool` does not exist yet. The checkpoint's child therefore looks it up with `vars(popular_videos).get(...)` rather than the plan draft's bare attribute access, which would have crashed every case during setup. The draw printed `[('none0', 0.0), ('z0', 0.0), ('hi0', 0.9000000357627869)]`: float32 `[s, sqrt(1-s²)]` against like `[1,0]` gives cosine ≈ s, negative and missing embeddings score 0.0, and scores are identical within a group. Under seed "probe:0", `expected ['none0', 'z0', 'hi0']` came out equal to the draw, and reseeding gave the same result again. So today's likes path is exactly `random.sample(ordered, limit)` with the stable, clamped descending order, and string seeds are deterministic. That is the observed basis for the C2 expected value.
2. `ValidateTests tests/tmp/probe_16_popular_margin.py -s` — the plan's reference Efraimidis–Spirakis draw, run under the checkpoint's seeds. It printed `skew hi 1773 lo 227 ratio 7.81`, while the uniform sample under the same seeds gave `hi 974 lo 1026`. Hence the bounds `hi >= 3*lo` (the weighted draw passes with margin, uniform fails) and `lo > 0` (a correct draw gives 227). zero_fill counts: p0, p1, p2 at 100 each; zero-weight ids between 20 and 37 each, so every one is covered within 100 trials.
3. `ValidateTests tests/tmp/probe_16_popular_harness.py -s` — imports `_CHILD` and `CASES` from the checkpoint and runs the child against today's code without running the checkpoint's tests. It printed `RC 0`. Results: skew hi 974 / lo 1026 (C1 fails, as it should today); zero_fill `all positives every draw False` (C1 fails); zero_unused has 605 non-positive ids (C1 fails); all_zero and all five disabled cases `equal_expected True` (C2 holds on today's uniform path); small_equal and small_under come back whole. A simulated wrong branch (`_random_from_pool` rerouted to `_weighted_from_pool` in disabled_zero) printed `WRONG-BRANCH RC 1 ... AssertionError: disabled_zero: weighted draw ran while disabled`, so the refusal guard does fire. My tools cannot delete files, so the three probe files (`tests/tmp/probe_16_popular_child.py`, `probe_16_popular_margin.py`, `probe_16_popular_harness.py`) are still on disk and should be removed. Their names don't match `test_*.py`, so default collection skips them.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_16_popular_weighted_random_phase1.py` - 7904 characters, inlined in full

```
"""Phase 1 checkpoint: the popular layer's likes path draws by similarity when `weighted_random_alpha` is positive.

- With likes and alpha 1.0, `limit` distinct candidates come back, the 0.9-similarity group outnumbers the 0.1 group at least 3:1 while the 0.1 group still appears, and zero-weight candidates (0.0, negative, missing embedding) appear only to fill a shortfall, spread over every one of them.
- With alpha missing, None, 0, -1.0 or NaN (weighted helper replaced by one that raises), or with every weight zero, each draw equals `random.sample(ordered, limit)` under the same seed.
- A pool of `limit` or fewer comes back whole.

`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
LIMIT = 5

_CHILD = textwrap.dedent(
    """
    import json, math, random, sys, threading
    from types import SimpleNamespace
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    import numpy as np
    from recommendations.candidates import popular_videos
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator

    # looked up, not required: the helper may not exist yet, and a missing one must not crash the uniform cases
    WEIGHTED = vars(popular_videos).get("_weighted_from_pool")
    SERVER = SimpleNamespace(db=None, db_lock=threading.Lock())

    def vector(sim):
        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)

    def generator(pool):
        table = {"like": np.array([1.0, 0.0], dtype=np.float32)}
        table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})
        return PopularVideosGenerator(PopularVideosDeps(
            fetch_popular_videos=lambda db, count: [{"video_id": vid} for vid in pool],
            fetch_recent_likes=lambda user_id, count: [{"video_id": "like"}],
            fetch_embeddings_by_ids=lambda db, rows: {r["video_id"]: table[r["video_id"]] for r in rows if r["video_id"] in table},
            like_key=lambda row: row["video_id"],
            max_likes=10,
        ))

    def refusing(name):
        def refuse(*args, **kwargs):
            raise AssertionError(f"{name}: weighted draw ran while disabled")
        return refuse

    def install(helper):
        if helper is None:
            vars(popular_videos).pop("_weighted_from_pool", None)
        else:
            popular_videos._weighted_from_pool = helper

    out = {}
    for case in json.loads(sys.argv[2]):
        pool, limit = case["pool"], case["limit"]
        config = {"pool_size": len(pool), "max_per_author": 0, "max_per_instance": 0}
        if "alpha" in case:
            config["weighted_random_alpha"] = float("nan") if case["alpha"] == "nan" else case["alpha"]
        install(refusing(case["name"]) if case.get("disabled") else WEIGHTED)
        # nominal similarity clamped at 0, stable descending, as the generator orders its scored pool
        ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)
        gen = generator(pool)
        draws, expected = [], []
        for trial in range(case["trials"]):
            random.seed(f"{case['name']}:{trial}")
            draws.append([row["video_id"] for row in gen.get_candidates(SERVER, "user", limit, config=config)])
            if case.get("uniform"):
                random.seed(f"{case['name']}:{trial}")
                expected.append(random.sample(ordered, limit))
        out[case["name"]] = {"draws": draws, "expected": expected}
    install(WEIGHTED)
    print(json.dumps(out))
    """
)


def _pool(**groups: tuple[int, float | None]) -> dict[str, float | None]:
    return {f"{prefix}{i}": sim for prefix, (count, sim) in groups.items() for i in range(count)}


HI_LO = _pool(hi=(10, 0.9), lo=(10, 0.1))
ZERO_FILL = {**_pool(p=(3, 0.5), z=(5, 0.0)), "neg0": -0.5, "none0": None}
DISABLED = {"disabled_missing": {}, "disabled_none": {"alpha": None}, "disabled_zero": {"alpha": 0}, "disabled_negative": {"alpha": -1.0}, "disabled_nan": {"alpha": "nan"}}
SMALL = {"small_equal": {"a": 0.9, "b": 0.5, "c": 0.0, "d": None, "e": 0.2}, "small_under": {"a": 0.9, "b": 0.0, "c": 0.4}}

CASES = [
    {"name": "skew", "pool": HI_LO, "alpha": 1.0, "limit": LIMIT, "trials": 400},
    {"name": "zero_fill", "pool": ZERO_FILL, "alpha": 1.0, "limit": LIMIT, "trials": 100},
    {"name": "zero_unused", "pool": _pool(p=(6, 0.5), z=(10, 0.0)), "alpha": 1.0, "limit": LIMIT, "trials": 200},
    {"name": "all_zero", "pool": {**_pool(z=(10, 0.0)), "neg0": -0.3, "none0": None}, "alpha": 1.0, "limit": LIMIT, "trials": 50, "uniform": True},
    *({"name": name, "pool": HI_LO, **extra, "limit": LIMIT, "trials": 50, "uniform": True, "disabled": True} for name, extra in DISABLED.items()),
    *({"name": name, "pool": pool, "alpha": 1.0, "limit": LIMIT, "trials": 3} for name, pool in SMALL.items()),
]


@pytest.fixture(scope="module")
def draws() -> dict[str, dict[str, list]]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(CASES)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr  # C2: a disabled case that reached the weighted helper raised in the child
    return json.loads(run.stdout)


def _assert_full_and_distinct(results: list[list[str]]) -> None:
    assert results
    for draw in results:
        assert len(draw) == LIMIT and len(set(draw)) == LIMIT, draw


def test_closer_candidates_are_drawn_at_least_three_times_as_often_and_never_twice(draws):
    results = draws["skew"]["draws"]
    _assert_full_and_distinct(results)  # C1
    hi = sum(vid.startswith("hi") for draw in results for vid in draw)
    lo = sum(vid.startswith("lo") for draw in results for vid in draw)
    assert hi >= 3 * lo, (hi, lo)  # C1: uniform gives ~1:1 (974:1026 under these seeds), the weighted draw ~8:1
    assert lo > 0, (hi, lo)  # C1: a draw, not a deterministic top-`limit` pick


def test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them(draws):
    filled = draws["zero_fill"]["draws"]
    _assert_full_and_distinct(filled)  # C1
    positives = {"p0", "p1", "p2"}
    fill_ids: set[str] = set()
    for draw in filled:
        assert positives <= set(draw), draw  # C1: every positive-weight candidate is taken before any zero-weight one
        fill_ids |= set(draw) - positives
    assert fill_ids == set(ZERO_FILL) - positives  # C1: the fill is drawn over every zero-weight candidate, not in pool order
    unused = draws["zero_unused"]["draws"]
    _assert_full_and_distinct(unused)  # C1
    assert [vid for draw in unused for vid in draw if not vid.startswith("p")] == []  # C1: enough positives, so no zero-weight id ever appears


def test_all_zero_weights_draw_exactly_the_uniform_sample(draws):
    case = draws["all_zero"]
    _assert_full_and_distinct(case["draws"])  # C2
    assert case["draws"] == case["expected"]  # C2


@pytest.mark.parametrize("name", list(DISABLED))
def test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample(draws, name):
    case = draws[name]
    _assert_full_and_distinct(case["draws"])  # C2
    assert case["draws"] == case["expected"]  # C2


@pytest.mark.parametrize("name", list(SMALL))
def test_a_pool_of_limit_or_fewer_comes_back_whole(draws, name):
    results = draws[name]["draws"]
    assert results
    for draw in results:
        assert sorted(draw) == sorted(SMALL[name])

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - red (audit round 1)

`tests/tmp/test_16_popular_weighted_random_phase1.py` exited 1.

```
  tests/tmp/test_16_popular_weighted_random_phase1.py  3 failed, 8 passed                     0.0s
  ---------------------------------------------------
  total                                                3 failed, 8 passed                     0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D5b

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this (rules/shape.md). It sits near `single-value-pin` but does not meet that entry's `<how_to_spot>`. tests/tmp/test_16_popular_weighted_random_phase1.py:76 and :111
   SKEW = {"skew": (1.0, 3), "skew_half": (0.5, 2)}
   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1
   The test runs two alpha values, but it checks each one against its own fixed floor and never compares one run with the other. An implementation that uses a fixed exponent whatever alpha is set to would give about 7.8:1 at alpha 0.5. That clears the 2:1 floor, so nothing here shows the output tracks alpha's size. C1 as written only asks that the weighting be "clearly" skewed, so this is not blocking. If alpha's size is meant to matter, assert that hi:lo at 1.0 is higher than hi:lo at 0.5.

PREDICTED FAILURE
Against the code as it stands, `get_candidates` ends in the uniform `random.sample(ordered, limit)` and ignores `weighted_random_alpha`. So both SKEW cases fail at line 111 on `assert hi >= SKEW[name][1] * lo` with roughly equal counts (the test's own comment records 974:1026 and 1042:958). The zero-weight test fails at line 121 on `assert positives <= set(draw)`, the first time a uniform draw leaves out one of p0–p2. The all-zero, disabled-alpha and small-pool tests pass, because they describe behaviour the current code already has.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist. It was not read.
2. `code_under_test` lists engine/server/api/server_config.py (EDITED). A Grep found no `weighted_random_alpha` key in it. The file was not read in full, and the test does not depend on it: it builds its own `config` dict at line 50.
3. `recommendations.filters.apply_author_instance_caps` was not read. The stub answer assumes that with both caps at 0 it keeps the pool order. The uniform-equality assertions at lines 132 and 139 depend on that order.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a short or overlong draw | CARRIED |
| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |
| C1c | must_prove | "closer candidates appear clearly more often" | :111 | a uniform sample (1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |
| C1d | must_prove | zero-weight candidates appear "only when there are too few positive-weight ones" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or one displacing a positive (zero_fill) | CARRIED |
| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |
| C2a | must_prove | missing alpha → exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG consumption | CARRIED |
| C2b | must_prove | None alpha → the same | :139 [disabled_none] | `None` handled as positive, or a crash | CARRIED |
| C2c | must_prove | zero alpha → the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that consumes RNG differently | CARRIED |
| C2d | must_prove | negative alpha → the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |
| C2e | must_prove | NaN alpha → the same | :139 [disabled_nan] | NaN passing a `<= 0` guard and reaching the weights | CARRIED |
| C2f | must_prove | every weight zero → the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |
| D1 | docstring | "likes path draws by similarity when `weighted_random_alpha` is positive" | :111 | an alpha-blind draw | CARRIED |
| D2 | docstring | "`limit` distinct candidates come back" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |
| D3 | docstring | "0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)" | :111 with `SKEW[name][1]` | a weak or absent skew at either alpha | CARRIED |
| D4 | docstring | "while the 0.1 group still appears" | :112 | a deterministic top-`limit` pick | CARRIED |
| D5a | docstring | 0.0-similarity candidates "appear only to fill a shortfall" | :126 | a 0.0 id drawn alongside enough positives | CARRIED |
| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :121, :123 | nothing: zero_fill has only 3 positives, so a negative or missing-embedding candidate given positive weight is one of 4 weighted items in a draw of 5. All positives still appear (:121) and the fill still covers every id (:123). zero_unused, the only surplus case (:126), has no negative or missing-embedding member | UNCARRIED |
| D6 | docstring | the fill is "spread over every one of them" | :123 | filling from pool order (always z0, z1) | CARRIED |
| D7 | docstring | "alpha missing, None, 0, -1.0 or NaN … each draw equals `random.sample(ordered, limit)`" | :139 | any non-identical draw under the same seed | CARRIED |
| D8 | docstring | "or with every weight zero" | :132 | as C2f | CARRIED |
| D9 | docstring | "`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order" | :139 on LO_HI (lo inserted first, :73–74) | sampling the unsorted pool | CARRIED |
| D10 | docstring | "A pool of `limit` or fewer comes back whole" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |
| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | a child that failed or never ran being read as results | CARRIED |
| N1a | name | "closer candidates are drawn clearly more often" | :111 | a uniform draw | CARRIED |
| N1b | name | "and never twice" | :101 | sampling with replacement | CARRIED |
| N2a | name | "zero weight candidates fill only a shortfall" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |
| N2b | name | "and spread over all of them" | :123 | a pool-order fill | CARRIED |
| N3 | name | "all zero weights draw exactly the uniform sample" | :132 | any draw other than the seeded sample | CARRIED |
| N4 | name | "a missing none zero negative or nan alpha draws exactly the uniform sample" | :139, parametrized over all five at :135 | any one disabled form leaking into a weighted draw | CARRIED |
| N5 | name | "a pool of limit or fewer comes back whole" | :147 | a partial or padded return | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_16_popular_weighted_random_phase1.py:3
   D5b is UNCARRIED. The docstring puts "negative, missing embedding" in the zero-weight set that "appear[s] only to fill a shortfall". The only case with surplus positives, `zero_unused` (:83, asserted at :126), contains only 0.0-similarity members. `zero_fill` (:75) holds just 3 positives against `limit` 5, so `neg0` or `none0` given positive weight still lets :121 and :123 pass. This clause is in the docstring and not in `must_prove`, so it is not a Critical. Either add `neg0`/`none0` to the `zero_unused` pool or narrow the docstring sentence.
2. bounds (rules/testing.md) — tests/tmp/test_16_popular_weighted_random_phase1.py:77
   The disabled-alpha edges are covered (missing, None, 0, negative, NaN). These inputs are not:
   - a positive infinite alpha
   - an empty popular pool
   - `limit` 0

   The phase's behaviour at those edges is therefore unasserted.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists `tests/active/test_popular_weighted_random.py` as NEW, but that path does not resolve. Whole-claim and bounds were judged from `test_path` and the two engine modules that do resolve.
2. `fixtures_path` was not supplied. The test's only fixture, `draws` (:90–95), is defined in `test_path`, so no conftest was needed to judge independence.

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - self-check (audit round 2, send-back 0)

`tests/tmp/test_16_popular_weighted_random_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_16_popular_weighted_random_phase1.py:101 (via _assert_full_and_distinct at :107, :117, :125): every skew, skew_half, zero_fill and zero_unused draw has exactly 5 distinct ids. :111: hi hits >= 3×lo at alpha 1.0 and >= 2×lo at 0.5. :112: lo > 0. :121: p0–p2 are in every zero_fill draw. :123: the zero_fill fill union equals all 7 zero-weight ids. :126: zero_unused (6 positives, plus 0.0, negative and missing-embedding ids) never draws a non-positive id. - expected: Reference draw: 1773:227 at alpha 1.0 and 1468:532 at 0.5. zero_fill positives appear in 100/100 draws and the fill covers z0–z4, neg0 and none0. zero_unused has 0 non-positive ids. - excludes: Today's uniform random.sample: 974:1026 and 1042:958 fail :111; a zero_fill draw missing a positive fails :121; zero_unused draws 663 non-positive ids (neg0 52, none0 54), which fails :126. Treating a missing embedding as weight 1.0 draws none0 185 times, and weighting a negative by abs draws neg0 147 times; both fail :126. A deterministic top-limit pick fails :112 (lo 0). A pool-order fill (always z0, z1) fails :123. Sampling with replacement fails :101.
- C2 - tests/tmp/test_16_popular_weighted_random_phase1.py:132: every all_zero draw (every weight 0 at alpha 1.0) equals random.sample(ordered, 5), recomputed under the same per-trial seed. :139, parametrized over missing/None/0/-1.0/NaN on LO_HI: each draw equals random.sample(ordered, 5) under the same seed. :101 via :131, :138 checks each draw is full and distinct. - expected: Draws are identical to the seeded uniform sample over the similarity-sorted pool: equal_expected True on today's code for all_zero and all five disabled cases. - excludes: Several wrong implementations make the list differ within 50 trials: a weighted draw that runs while alpha is disabled (NaN slipping past a `<= 0` guard, or `sim**0 == 1` treated as weighted), extra RNG consumption, or an all-zero pool that takes the weighted/fill path. Sampling the unsorted, low-first pool also differs, because LO_HI inserts lo first.

<items>
<item id="D5b">
<disposition>fixed</disposition>
<what>Added `"neg0": -0.5` and `"none0": None` to the `zero_unused` pool at :83, which becomes 6 at 0.5, 10 at 0.0, one negative and one with no embedding. The docstring clause now has a surplus-positive case covering every zero-weight kind it names. :126 now carries it: `[vid for draw in unused for vid in draw if not vid.startswith("p")] == []` fails on any `neg0` or `none0` draw. The comment on that line now names all three kinds. A wrong implementation that weights a missing embedding as 1.0 gives none0 185 hits over the 200 trials, and one that weights a negative by `abs` gives neg0 147 hits. The correct reference draw gives 0 (seen in probe_16_zero_unused). `neg0` and `none0` do reach the scored pool, because :123 requires both in the zero_fill union. That is the positive control for this absence assertion.</what>
</item>
</items>

<findings_addressed>
No CRITICAL from either auditor. Claim rec 1 (D5b uncarried): taken. neg0/none0 added to the zero_unused pool at :83, so :126 now carries it (see item D5b). Claim rec 2 (inf alpha, empty pool, limit 0): not taken. No clause in C1/C2 or the docstring names those edges, and adding them would grow the checkpoint beyond the phase's must_prove. Shape rec 1 (no cross-alpha comparison): not taken. C1 asks for a "clearly more often" skew, not a monotonic dependence on alpha's size, and the auditor marks it non-blocking.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:101 (via _assert_full_and_distinct at :107, :117, :125): every skew, skew_half, zero_fill and zero_unused draw has exactly 5 distinct ids. :111: hi hits >= 3×lo at alpha 1.0 and >= 2×lo at 0.5. :112: lo > 0. :121: p0–p2 are in every zero_fill draw. :123: the zero_fill fill union equals all 7 zero-weight ids. :126: zero_unused (6 positives, plus 0.0, negative and missing-embedding ids) never draws a non-positive id.</assertion>
<expected>Reference draw: 1773:227 at alpha 1.0 and 1468:532 at 0.5. zero_fill positives appear in 100/100 draws and the fill covers z0–z4, neg0 and none0. zero_unused has 0 non-positive ids.</expected>
<wrong_implementation>Today's uniform random.sample: 974:1026 and 1042:958 fail :111; a zero_fill draw missing a positive fails :121; zero_unused draws 663 non-positive ids (neg0 52, none0 54), which fails :126. Treating a missing embedding as weight 1.0 draws none0 185 times, and weighting a negative by abs draws neg0 147 times; both fail :126. A deterministic top-limit pick fails :112 (lo 0). A pool-order fill (always z0, z1) fails :123. Sampling with replacement fails :101.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_16_popular_weighted_random_phase1.py:132: every all_zero draw (every weight 0 at alpha 1.0) equals random.sample(ordered, 5), recomputed under the same per-trial seed. :139, parametrized over missing/None/0/-1.0/NaN on LO_HI: each draw equals random.sample(ordered, 5) under the same seed. :101 via :131, :138 checks each draw is full and distinct.</assertion>
<expected>Draws are identical to the seeded uniform sample over the similarity-sorted pool: equal_expected True on today's code for all_zero and all five disabled cases.</expected>
<wrong_implementation>Several wrong implementations make the list differ within 50 trials: a weighted draw that runs while alpha is disabled (NaN slipping past a `<= 0` guard, or `sim**0 == 1` treated as weighted), extra RNG consumption, or an all-zero pool that takes the weighted/fill path. Sampling the unsorted, low-first pool also differs, because LO_HI inserts lo first.</wrong_implementation>
</row>
</rows>

<answers>
1. No. :126 is an absence assertion, but three things arm it. :125 requires 5 distinct ids in each of the 200 draws. :123 shows neg0 and none0 reach the scored pool in zero_fill. Today's code draws 663 non-positive ids in zero_unused. Delete the weighting and :126 goes red.
2. No. The expected values in :132 and :139 are recomputed in the child with random.sample on the similarity order under the same seed. That is the disabled-path contract, not production's transformation. If production's weighted branch were taken instead, the lists would differ. :126 compares against a literal empty list, derived from the pool's positive/zero split.
3. No. The skew is read at two alphas over 400 trials each. The zero-weight behaviour is read in a shortfall case and a surplus case. C2 is read across five disabled forms plus all-zero, 50 trials each.
4. No. The only doubles are the PopularVideosDeps fetch lambdas (DB and embedding store, a severed layer) and a SimpleNamespace server. PopularVideosGenerator and the draw logic run for real.
5. Yes, it collects. This edit changes only a dict literal and a comment. Line numbers are unchanged, and probe_16_zero_unused imports the checkpoint module and ran the edited zero_unused case in the Engine child with RC 0.
6. Yes. The new expected value (zero_unused never draws neg0 or none0) is observed from the probe's reference draw: 0 non-positive ids. The wrong variants were observed at 185 and 147 hits, and today's code at 663.
7. Yes, it is still red for its own reason. Today's code makes the skew tests fail at :111 and the zero-weight test fail at :121, and it would also fail at :126 (neg0 52 and none0 54 among 663 non-positive ids). The C2 and small-pool tests pass on today's uniform path, as intended. My tools cannot delete files, so tests/tmp/probe_16_zero_unused.py (and the earlier probe_16_* files) remain and should be removed. None of them match test_*.py.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - red (audit round 2)

`tests/tmp/test_16_popular_weighted_random_phase1.py` exited 1.

```
  tests/tmp/test_16_popular_weighted_random_phase1.py  3 failed, 8 passed                     0.0s
  ---------------------------------------------------
  total                                                3 failed, 8 passed                     0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this; it is nearest to single-value-pin (rules/shape.md) — tests/tmp/test_16_popular_weighted_random_phase1.py:111
   assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1
   The test runs alpha 1.0 and alpha 0.5, but each is checked alone against its own ratio (3:1 and 2:1). Nothing checks that the two draws differ from each other. An implementation that ignores alpha and always weights as if alpha were 1.0 would give about 7.8:1 at both values and pass both. That does not break a stated entry: this is not one input, and C1 does not say the skew must follow alpha. If alpha is meant to control how strong the skew is, asserting that alpha 1.0 skews more than alpha 0.5 would make that part of the gate, following the entry's `<alternatives>`.

PREDICTED FAILURE
Against the current code, which only ever calls `random.sample(ordered, limit)`, the test should fail in two places:
- `test_closer_candidates_are_drawn_clearly_more_often_and_never_twice[skew]` and `[skew_half]` should fail at line 111. `hi >= SKEW[name][1] * lo` does not hold because the uniform draw gives about 974:1026 and 1042:958.
- `test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them` should fail at line 121. `positives <= set(draw)` does not hold because a uniform 5-of-10 draw leaves out some of p0–p2.

These tests should pass against the current code:
- `test_all_zero_weights_draw_exactly_the_uniform_sample`
- the five `test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample` cases
- the two `test_a_pool_of_limit_or_fewer_comes_back_whole` cases

That is expected: C2 says the old draw must stay the same, so these tests pass on the old code. They still catch wrong implementations: weighting that leaks into the disabled or all-zero path, or sampling in pool order instead of similarity order. They would fail on either.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not exist yet. Nothing in it was assessed.
2. Whether `ENGINE_PY` (engine/.pixi/envs/default/bin/python) exists was not checked. If it is missing, the `draws` fixture fails at line 92 before any test assertion runs, and the prediction above does not hold.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (30 clauses: 11 must_prove, 12 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | with likes and positive alpha, returns `limit` candidates | :101 (via :107, :117, :125) | a draw that is too short or too long | CARRIED |
| C1b | must_prove | the candidates are distinct | :101 `len(set(draw)) == LIMIT` | drawing with replacement | CARRIED |
| C1c | must_prove | "closer candidates appear clearly more often" | :111 | a uniform sample (about 1:1 against a 3:1 / 2:1 floor), or alpha ignored | CARRIED |
| C1d | must_prove | zero-weight candidates appear "only when there are too few positive-weight ones" | :126, :121 | a zero-weight id drawn while positives remain (zero_unused), or a zero-weight id pushing out a positive (zero_fill) | CARRIED |
| C1e | must_prove | zero-weight candidates do fill a shortfall up to `limit` | :117 (:101 on zero_fill, 3 positives, limit 5) | dropping zero-weight candidates and returning fewer than `limit` | CARRIED |
| C2a | must_prove | missing alpha → exactly `random.sample(ordered, limit)` under the same seed | :139 [disabled_missing] | a weighted draw when the key is absent, or extra RNG use | CARRIED |
| C2b | must_prove | None alpha → the same | :139 [disabled_none] | `None` treated as positive, or a crash | CARRIED |
| C2c | must_prove | zero alpha → the same | :139 [disabled_zero] | `sim**0 == 1` taken as a weighted path that uses the RNG differently | CARRIED |
| C2d | must_prove | negative alpha → the same | :139 [disabled_negative] | an inverse-weighted draw | CARRIED |
| C2e | must_prove | NaN alpha → the same | :139 [disabled_nan] | NaN getting past a `<= 0` guard and reaching the weights | CARRIED |
| C2f | must_prove | every weight zero → the same | :132 | a weighted path with all-zero keys, or a fill in pool order | CARRIED |
| D1 | docstring | "likes path draws by similarity when `weighted_random_alpha` is positive" | :111 | a draw that ignores alpha | CARRIED |
| D2 | docstring | "`limit` distinct candidates come back" at alpha 1.0 or 0.5 | :101 via :107 | short or duplicated draws | CARRIED |
| D3 | docstring | "0.9 group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5)" | :111 with `SKEW[name][1]` | a weak or missing skew at either alpha | CARRIED |
| D4 | docstring | "while the 0.1 group still appears" | :112 | a fixed top-`limit` pick | CARRIED |
| D5a | docstring | 0.0-similarity candidates "appear only to fill a shortfall" | :126 | a 0.0 id drawn when there are enough positives | CARRIED |
| D5b | docstring | negative and missing-embedding candidates count as zero-weight and so also fill only a shortfall | :126 (zero_unused pool at :83 now includes `neg0` -0.5 and `none0` None) | a negative or missing-embedding candidate given positive weight: it would be one of 8 weighted items for 5 slots over 200 trials, and :126 rejects any non-`p` id | CARRIED |
| D6 | docstring | the fill is "spread over every one of them" | :123 | filling in pool order (always z0, z1) | CARRIED |
| D7 | docstring | "alpha missing, None, 0, -1.0 or NaN … each draw equals `random.sample(ordered, limit)`" | :139 | any draw that differs under the same seed | CARRIED |
| D8 | docstring | "or with every weight zero" | :132 | same as C2f | CARRIED |
| D9 | docstring | "`ordered` being the pool sorted by similarity rather than the pool's own (low-first) order" | :139 on LO_HI (lo inserted first, :73–74) | sampling the unsorted pool | CARRIED |
| D10 | docstring | "A pool of `limit` or fewer comes back whole" | :147 | truncating, dropping zero-weight or None-embedding members, duplicating | CARRIED |
| D11 | docstring | every case runs in one Engine-interpreter child, reseeded per trial | :94 | reading a child that failed or never ran as if it gave results | CARRIED |
| N1a | name | "closer candidates are drawn clearly more often" | :111 | a uniform draw | CARRIED |
| N1b | name | "and never twice" | :101 | sampling with replacement | CARRIED |
| N2a | name | "zero weight candidates fill only a shortfall" | :121, :126 | zero-weight ids drawn while positives are available | CARRIED |
| N2b | name | "and spread over all of them" | :123 | a fill in pool order | CARRIED |
| N3 | name | "all zero weights draw exactly the uniform sample" | :132 | any draw other than the seeded sample | CARRIED |
| N4 | name | "a missing none zero negative or nan alpha draws exactly the uniform sample" | :139, parametrized over all five at :135 | any one disabled form slipping into a weighted draw | CARRIED |
| N5 | name | "a pool of limit or fewer comes back whole" | :147 | a partial or padded return | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_16_popular_weighted_random_phase1.py:83
   D5b, UNCARRIED in the ledger, is now carried because an assertion was added: the zero_unused pool at :83 now includes `neg0` (-0.5) and `none0` (None). The docstring sentence was not narrowed, and :126 now excludes a positive weight on either member.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_popular_weighted_random.py (NEW), which does not resolve. It could not be read or compared with the file under audit.
2. `code_under_test` lists engine/server/api/server_config.py (EDITED), but it contains no `weighted_random_alpha`. I could not judge from it how a real config supplies alpha or its default. The test passes `config` directly into `get_candidates` (tests/tmp/test_16_popular_weighted_random_phase1.py:50–52, :59), so the verdict stands on that seam alone.

## 2026-09-28 - Step 7 - Phase 1 (Similarity-weighted popular draw) - checkpoint outcome (run 1)

`tests/tmp/test_16_popular_weighted_random_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/recommendations/candidates/popular_videos.py`
- `get_candidates` reads `weighted_random_alpha` from the per-generator config as `float(config.get("weighted_random_alpha") or 0.0)`. If the value is positive, the end of the likes path now calls the new `_weighted_from_pool(scored, limit, alpha)`. If it is missing, None, 0, negative or NaN (`not alpha > 0` also catches NaN), the path does exactly what it did before: `_random_from_pool(ordered, limit)` over the pool sorted by similarity. The early returns for no likes, missing embeddings and no usable liked vectors are unchanged and still draw uniformly.
- New `_weighted_from_pool`:
  - Each candidate's weight is `similarity ** alpha`, or 0.0 if its clamped similarity is not positive.
  - Candidates are split on the weight, not the score, so a tiny score that underflows to 0 under a large alpha can't cause a divide-by-zero.
  - If no weight is positive, it hands the same similarity-ordered list to `_random_from_pool`. It uses no randomness before that, so the result is exactly the uniform sample under the same seed.
  - A pool of `limit` or fewer comes back whole.
  - Otherwise it runs an Efraimidis-Spirakis draw without replacement over the positive-weight candidates, keyed on `log(1 - u) / w` (the log form avoids `u ** (1/w)` underflowing to ties) and keeps the top `limit` keys.
  - If there are fewer positive-weight candidates than `limit`, the gap is filled with `random.sample` over all zero-weight candidates.
- Added `import math`.

### `engine/server/api/server_config.py`
- Added `"weighted_random_alpha": 1.0` to the `popular` generator in the `home` and `upnext` profiles, with a one-line comment on the `home` entry. `guest_home` and `guest_upnext` are unchanged; guests have no likes, so they would never reach the weighted path anyway.

### `tests/active/test_popular_weighted_random.py`
- I didn't write this file. The phase lists it as NEW, but the gating checkpoint is `tests/tmp/test_16_popular_weighted_random_phase1.py`, and I didn't touch that either. Presumably the workflow moves it into place later.
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
  tests/tmp/test_16_popular_weighted_random_phase1.py  11 passed                              0.0s
  ---------------------------------------------------
  total                                                11 passed                              0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_16_popular_weighted_random_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_16_popular_weighted_random_phase1.py`

## 2026-09-28 - Step 8 - refactor pass

<refactors>
engine/server/api/recommendations/candidates/popular_videos.py: in `_weighted_from_pool`, the all-zero exit and the small-pool exit (`len(scored) <= limit`) are now one `if not positive or len(scored) <= limit:` that returns `_random_from_pool` over the similarity-ordered list. `_random_from_pool` already returns a pool of `limit` or fewer whole, so the separate list comprehension and early return are gone. The branch comment now explains why both cases go there.
</refactors>

<left_out>
Moving the `weighted_random_alpha` read up to join the other config reads at the top of `get_candidates`, as the impacts step suggested. It is not a pure refactor: a non-numeric alpha would then raise `float()` on the no-likes and no-embedding paths too, where today it never gets read. The three copies of the timing-log-then-`_random_from_pool` early return in `get_candidates` were there before this build and this phase did not touch them, so pulling them into a helper would widen the diff past the approved scope. The odd import order (`import random` and `from time import perf_counter` sit below numpy) is also older than this build, so I left it alone. I made no change to `server_config.py`: the two added keys and the one comment on `home` are already as small as they can be. I also had no way to delete `tests/tmp/probe_16_refactor_equivalence.py` (there is no delete tool), so I emptied it. The workflow or the operator should remove it.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
I checked the merge with a probe rather than the gating suite. It copied the old and new `_weighted_from_pool` side by side and ran them on 20,000 random cases (score 0, scores that underflow under alpha 200, pools smaller and larger than `limit`), each pair under the same seed. The returned lists and the RNG state afterwards were identical every time, so the refactor keeps the byte-for-byte uniform fallback the C2 checkpoint needs. The call site stays a module-global `_weighted_from_pool`, so the checkpoint's refusing patch still intercepts it. I did not run the gating test `tests/tmp/test_16_popular_weighted_random_phase1.py` myself; the workflow's run is the one that confirms it.
</observation>

## 2026-09-28 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 6 of 27 test groups (21 unchanged):
  test_dislike_profile.py — changed
  test_internal_events.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_server_config.py — changed
  test_similar.py — changed
  test_dislike_profile.py  5 passed                              17.5s
  test_internal_events.py  9 passed                               0.6s
  test_search_fusion.py    10 passed                              2.4s
  test_server.py           70 passed                             28.2s
  test_server_config.py    20 passed                              6.3s
  test_similar.py          32 passed                             34.2s
  -----------------------
  total                    146 passed                            34.5s wall, 6 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 9 - document triage

- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - In the "popular Layer" section, add `generators.popular.weighted_random_alpha` to the Layer Params list, glossed as the draw-weight exponent used when likes exist. It defaults to 1.0 in `home` and `upnext`, and 0, negative, NaN or a missing value disables it. Replace the Behavior sentence at lines 149-150, "with likes, the pool is re-ranked by similarity; otherwise it is returned as-is (popularity with a soft freshness bonus)". Every clause of it is false: the code never returned the pool as-is, and there is no freshness bonus. The new text describes the delivered state. With likes and alpha > 0, the layer draws `limit` entries without replacement, weighted by `similarity ** alpha`, and zero-weight entries only fill a shortfall, uniformly. With alpha disabled, or when every weight is zero, it takes a uniform random sample. Without likes or usable embeddings, it takes a uniform random sample of the capped pool. A pool of `limit` or fewer entries is returned whole. It should also note that the key only has an effect in `home`, because up-next does not run the layers (line 154 already says so).
- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md` - §3, the popular bullet at lines 78-83: "If likes exist, it is re-ranked by similarity. / Selection: random sample from the pool after sorting." becomes the delivered behaviour. With likes, selection is a draw without replacement weighted by `similarity ** weighted_random_alpha`. Otherwise it is a uniform random sample. §4, line 109, popular pool: "if likes exist, re-ranked by similarity; then caps" has the order wrong and describes a ranking. Rewrite it as caps first, then a similarity-weighted draw when likes exist.
- [ ] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - Line 34: the Mermaid node `H3[Popular pool<br/>rank by similarity if likes]` describes a ranking, but the layer does a draw. Relabel it to something like `H3[Popular pool<br/>similarity-weighted draw if likes]`, keeping `<br/>` and avoiding `**` and parentheses inside the brackets so the Mermaid still parses.
- [ ] `docs/project/issues/16-popular-weighted-random.md` - The issue is delivered. Set the Status line to `enhancement, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`. Add a Comments note recording two decisions. The issue's "optionally with a small epsilon" is resolved as no epsilon, so with likes, popular videos with zero similarity only fill a shortfall. The key is `generators.popular.weighted_random_alpha`, set to 1.0 in `home`/`upnext`, and it only has an effect in `home`.
- [ ] `docs/project/roadmap.md` - Add a Delivered line for issue `16` in the format of the existing Delivered entries. It should say that, with likes, the home feed's popular layer is a similarity-weighted draw, name `generators.popular.weighted_random_alpha` (default 1.0, 0 disables) and link the plan `docs/project/plans/20-16-popular-weighted-random.md`. In the F3-M3 "Related" list at line 58, drop `16` or mark it delivered, so that only `17` is outstanding.
- [ ] `docs/project/issues/plan.md` - In the Wave 2 table, lane 2c (line 72) lists issue 16 as pending, and issue 16 has now been delivered. Mark it "Delivered." the same way lane 2a is marked. The files listed for the lane (`popular_videos.py`, `server_config.py`) are accurate and stay as they are.

Out of scope:
_none - this build changes no documented behaviour._

ADR conflicts: none

## 2026-09-28 - Step 9 - Update documentation

- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md "popular Layer": added `generators.popular.weighted_random_alpha` to the params list and replaced the incorrect Behavior sentence with a description of the similarity-weighted draw.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular entries in §3 and §4 now describe the similarity-weighted draw, and the §4 pool line applies caps before the draw.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Relabelled the popular pool node so it shows a similarity-weighted draw rather than a similarity ranking.
- [x] `docs/project/issues/16-popular-weighted-random.md` - updated: Issue 16 is marked `enhancement, complete` and copied to `docs/project/issues/archive/`, with a Delivered note. The original at `docs/project/issues/16-popular-weighted-random.md` still has to be deleted.
- [x] `docs/project/roadmap.md` - updated: Roadmap: added a Delivered entry for issue `16` (similarity-weighted popular draw) and removed `16` from the outstanding F3-M3 and Feed ordering lines.
- [x] `docs/project/issues/plan.md` - updated: Marked Wave 2 lane 2c (issue 16, popular weighted random) as delivered in `docs/project/issues/plan.md`.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/16-popular-weighted-random.md`: docs/project/issues/16-popular-weighted-random.md: this is the original, unedited, and the operator or the workflow needs to delete it to finish the move into archive/ (I have no delete tool).

**ADR conflicts.** none

### `engine/server/api/recommendations/docs/LAYER_PARAMS.md`

<changes>
LAYER_PARAMS.md "popular Layer": added `generators.popular.weighted_random_alpha` to the params list and replaced the incorrect Behavior sentence with a description of the similarity-weighted draw.

- New param entry: the exponent on the draw weight when the user has likes. It is 1.0 in `home` and `upnext`. A missing, 0, negative or NaN value turns weighting off. It only affects `home`, because up-next does not run the layers.
- The Behavior section now reads:
  - Author and instance caps are applied first.
  - A pool of `limit` or fewer entries is returned whole.
  - With likes and alpha > 0, it draws without replacement, weighted by `similarity_score ** alpha`. Zero-weight entries only fill a shortfall, picked uniformly.
  - With weighting off, or when every weight is zero, it takes a uniform sample.
  - Without likes or usable embeddings, it takes a uniform sample.
- One line notes there is no diversity term, so videos with zero similarity to the likes only come out to fill a shortfall.
- Removed the old sentence ("otherwise it is returned as-is (popularity with a soft freshness bonus)").
- I checked all of this against `popular_videos.py` (`get_candidates`, `_weighted_from_pool`, `_random_from_pool`, `_max_similarity`), and checked that `server_config.py` sets the key only in the `home` (line 97) and `upnext` (line 232) profiles.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/recommendations/docs/OVERVIEW.md`

<changes>
OVERVIEW.md: the popular entries in §3 and §4 now describe the similarity-weighted draw, and the §4 pool line applies caps before the draw.

- §3, popular bullet: the old "re-ranked by similarity" and "random sample from the pool after sorting" lines are replaced. With likes, each entry gets a `similarity_score` against the likes, and the layer draws without replacement, weighted by `similarity ** weighted_random_alpha`. Otherwise it takes a uniform random sample from the pool. The bullet points to `LAYER_PARAMS.md`, "popular Layer", for the key's default, how it is disabled, the zero-weight fill and the small-pool case, and does not repeat them here.
- §4, popular pool line: the order is now caps first, then a similarity-weighted draw if likes exist, as `get_candidates` does it (`apply_author_instance_caps` runs before scoring and `_weighted_from_pool`).

I checked the text against `popular_videos.py`: the `alpha` read and the `not alpha > 0` branch, and the weight `score**alpha` in `_weighted_from_pool`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md`

<changes>
Relabelled the popular pool node so it shows a similarity-weighted draw rather than a similarity ranking.

- Line 34: `H3[Popular pool<br/>rank by similarity if likes]` → `H3[Popular pool<br/>similarity-weighted draw if likes]`. I checked the label against `popular_videos.py`: when there are likes and `weighted_random_alpha` is above 0, `get_candidates` ends in `_weighted_from_pool` (lines 131-136). The new label keeps `<br/>` and has no `**` or parentheses, so the Mermaid still parses.
- I didn't change anything else. The alpha key, the fallback cases and the `home`-only scope belong to `LAYER_PARAMS.md` and `OVERVIEW.md`, and the diagram already points to those files.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/16-popular-weighted-random.md`

<changes>
Issue 16 is marked `enhancement, complete` and copied to `docs/project/issues/archive/`, with a Delivered note. The original at `docs/project/issues/16-popular-weighted-random.md` still has to be deleted.

- **Status.** Changed from `enhancement, needs-triage` to `enhancement, complete`, following `docs/project/triage-labels.md`.
- **Move.** The file is now at `docs/project/issues/archive/16-popular-weighted-random.md`. I have no delete tool, so the old copy is still in the open issues directory, unchanged. It needs to be deleted to finish the move.
- **Problem, Proposed solution and Related.** Left as the original request.
- **New Comments entry, "### Delivered".** It follows the format of `archive/14-collapsible-description.md`:
  - It links the plan `docs/project/plans/20-16-popular-weighted-random.md` with commit `<pending>`.
  - **No epsilon:** with likes, popular videos with zero similarity only fill a shortfall. Variety comes from the random, fresh and explore layers.
  - **Key:** the setting is `generators.popular.weighted_random_alpha`, 1.0 in `home` and `upnext`. It only has an effect in `home`, because up-next does not run the layers.
  - **Behaviour:** the note points to the "popular Layer" section of `LAYER_PARAMS.md` rather than repeating the draw rules.
- **Checked against the code.** The key is read in `popular_videos.py:131`. It is set only in the `home` and `upnext` profiles in `server_config.py` (lines 97 and 232). `_weighted_from_pool` fills a shortfall uniformly from zero-weight entries. `LAYER_PARAMS.md` line 159 says up-next does not run the layers.
- **Other references to the old path.** `17-feed-modes.md` refers to issue 16 by its slug, so it still works after the move. The plan and record files are generated by the workflow, so I didn't edit them.
</changes>

<not_on_checklist>
docs/project/issues/16-popular-weighted-random.md: this is the original, unedited, and the operator or the workflow needs to delete it to finish the move into archive/ (I have no delete tool).
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Roadmap: added a Delivered entry for issue `16` (similarity-weighted popular draw) and removed `16` from the outstanding F3-M3 and Feed ordering lines.

- **Delivered**: new entry "F3-M3, issue `16`, similarity-weighted popular draw". When the visitor has likes, the home feed's popular layer draws candidates weighted by similarity to those likes instead of uniformly. The entry names `generators.popular.weighted_random_alpha` (1.0 by default, 0 disables it) and points to `LAYER_PARAMS.md`, "popular Layer", for the full behaviour rather than repeating it. It links `docs/project/plans/20-16-popular-weighted-random.md`, which exists.
- **M3, F3-M3**: the line says issue `16` is delivered, so "Related" now lists only `17-feed-modes`.
- **Implementation order**: the Feed line was `16` -> `17` and is now just `17`, because that section lists open work only. The checklist did not name this line, but leaving it would have shown a delivered issue as still pending.

I checked the facts against the code. `server_config.py` sets `"weighted_random_alpha": 1.0` under `popular` in `home` (line 97) and `upnext` (line 232). `popular_videos.py:131` reads it as `float(config.get("weighted_random_alpha") or 0.0)`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/plan.md`

<changes>
Marked Wave 2 lane 2c (issue 16, popular weighted random) as delivered in `docs/project/issues/plan.md`.

- Line 72, the Wave 2 table: the "Depends on" cell for lane 2c changed from `none` to `none. Delivered.`. This follows lane 2a, which writes its dependency first and then "Delivered.".
- The lane's file list (`api/recommendations/candidates/popular_videos.py`, `server_config.py`) is unchanged and matches the code: `popular_videos.py` reads `weighted_random_alpha` and defines `_weighted_from_pool`, and `server_config.py` sets `"weighted_random_alpha": 1.0` in two profiles.
- Nothing else in the file changed. The P3 row (`16, 17`) and wave 6's dependency on 16 still read correctly as history. I did not strike 16 in the Priorities table, since the checklist asked only for the lane marker.
</changes>

<not_on_checklist>
none
</not_on_checklist>

## 2026-09-28 - Step 10 - Harvest tests - plan approved

Approved by the operator.

<harvest_file>
docs/project/plans/harvest-16-popular-weighted-random-plan.md
</harvest_file>

<plan>
## Harvest plan: 16 popular weighted random

The scope is `tests/tmp/test_16_popular_weighted_random_phase1.py`. It collects 11 items from 5 test functions. It drives `engine/server/api/recommendations/candidates/popular_videos.py` through `PopularVideosGenerator.get_candidates`, running in a child process on the Engine's interpreter.

**Verdicts**
- `DURABLE`: 5
- `REPLACES`: 0
- `COMBINE`: 0
- `REDUNDANT`: 0
- `SPENT`: 0

**Nothing in `tests/active` covers this generator.** No file there mentions `PopularVideosGenerator`, `popular_videos`, `weighted_random_alpha`, `_weighted_from_pool` or `_random_from_pool`. `test_random_videos.py` tests the SQL order of `data/random_videos.fetch_popular_videos`, which is a different producer.

**`DURABLE`: all five tests go to the new `tests/active/test_popular_videos.py`**
1. `test_closer_candidates_are_drawn_clearly_more_often_and_never_twice` (skew, skew_half): with a positive alpha, `limit` distinct ids come back, the 0.9 group beats the 0.1 group at least 3:1 at alpha 1.0 and 2:1 at alpha 0.5, and the 0.1 group still appears. (C1)
2. `test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them`: zero-weight ids (0.0, negative, missing embedding) only fill a shortfall, and the fill covers all of them. (C1)
3. `test_all_zero_weights_draw_exactly_the_uniform_sample`: when every weight is zero, the result is exactly `random.sample(ordered, limit)` under the same seed. (C2)
4. `test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample` (missing, None, 0, -1.0, NaN): a disabled alpha gives exactly the uniform sample over the similarity-ordered pool. (C2)
5. `test_a_pool_of_limit_or_fewer_comes_back_whole` (small_equal, small_under): regression guard that a pool of `limit` or fewer comes back whole.

The module fixtures and constants move with the tests unchanged: the `_CHILD` script, `ENGINE_PY`, `SERVER_DIR`, `LIMIT`, `_pool`, the pools, `CASES`, the `draws` fixture and `_assert_full_and_distinct`. The docstring's "Phase 1 checkpoint" wording is rewritten to state the rules the tests check.

**Retired from `active`:** none.

**`test_groups` change:** one new entry, and no existing entry changes:
- `"test_popular_videos.py": ["engine/server/api/recommendations/candidates/popular_videos.py"]`
- `server_config.py` is not claimed, because every case passes its own config dict. So the `weighted_random_alpha: 1.0` added to the `home` and `upnext` profiles stays untested by this harvest.

**New subject file Step 5 would create:** `tests/active/test_popular_videos.py`. It is a new group and gets the new map entry above. The phase plan called the file `tests/active/test_popular_weighted_random.py`; harvest names it after the production script instead.

**Things to know before approving**
- **Probe scripts left in `tests/tmp`:** six `probe_16_*.py` files (`popular_child`, `popular_harness`, `popular_margin`, `refactor_equivalence`, `reference_draw`, `zero_unused`). They are outside the scope I was given, so Step 7 moves only the test file to `delete_me/` and `tests/tmp` will not end up empty. Say if you want them moved too.
- **Mutation caveat:** all five tests share one module-scoped `draws` fixture that checks the child process's return code. Any mutation that crashes the child would fail all five tests at once, which proves nothing about the named test. So each Step 6 mutation has to change only the draw and keep the child running.
- **Checkpoint description is wrong on one point:** it says the disabled cases replace `_weighted_from_pool` with a stub that raises. The file doesn't do that; it only compares the draws with the seeded uniform sample. It moves as written.

**Done so far:** `tests/last_test_validation.json.preharvest` is taken and `cmp`-identical to the record. Nothing has moved, and neither the group map nor any production file has been touched.
</plan>

## 2026-09-28 - Step 10 - Harvest tests

<moved>
tests/tmp/test_16_popular_weighted_random_phase1.py::test_closer_candidates_are_drawn_clearly_more_often_and_never_twice (skew, skew_half) -> tests/active/test_popular_videos.py, new group test_popular_videos.py
tests/tmp/test_16_popular_weighted_random_phase1.py::test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them -> tests/active/test_popular_videos.py, new group test_popular_videos.py
tests/tmp/test_16_popular_weighted_random_phase1.py::test_all_zero_weights_draw_exactly_the_uniform_sample -> tests/active/test_popular_videos.py, new group test_popular_videos.py
tests/tmp/test_16_popular_weighted_random_phase1.py::test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample (missing, None, 0, -1.0, NaN) -> tests/active/test_popular_videos.py, new group test_popular_videos.py
tests/tmp/test_16_popular_weighted_random_phase1.py::test_a_pool_of_limit_or_fewer_comes_back_whole (small_equal, small_under) -> tests/active/test_popular_videos.py, new group test_popular_videos.py
The module fixtures and constants moved unchanged: _CHILD, ROOT, SERVER_DIR, ENGINE_PY, LIMIT, _pool, the pools, CASES, the draws fixture and _assert_full_and_distinct. Only the docstring's first line changed: "Phase 1 checkpoint: ..." became the rule it gates.
</moved>

<retired>
none
</retired>

<group_map>
Added "test_popular_videos.py": ["engine/server/api/recommendations/candidates/popular_videos.py"] to test_groups in .un/skills/devsecops/config.json, as the last key. No existing entry changed, and server_config.py is not claimed. The sandbox (confine_un_dir) blocked my edit to .un/, so the operator made this exact edit at my request, and I verified it by reading config.json. --audit-map exits 0, with no MISSING finding for test_popular_videos.py. It does show BARREN for test_popular_videos.py, as it does for 13 other groups that already existed.
</group_map>

<mutations>
test_closer_candidates_are_drawn_clearly_more_often_and_never_twice: in _weighted_from_pool the key `math.log(1.0 - random.random()) / weight` became `/ 1.0` (uniform over positives). RED on both params at line 111 `assert hi >= SKEW[name][1] * lo`, with (958, 1042) at alpha 1.0 and (1008, 992) at 0.5. Restored from .bak1, diff clean, GREEN 2 passed.
test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them: the shortfall fill `random.sample(zero, limit - len(picked))` became `zero[: limit - len(picked)]` (pool order). RED at line 123 `assert fill_ids == set(ZERO_FILL) - positives`, where the fill was only {z0, z1} and neg0, none0, z2, z3, z4 were missing. Restored from .bak2, diff clean, GREEN 1 passed.
test_all_zero_weights_draw_exactly_the_uniform_sample: the no-positive fallback sampled `reversed(scored)` instead of the similarity order. RED at line 132 `assert case["draws"] == case["expected"]`, where the draws differed at index 0. Restored from .bak3, diff clean, GREEN 1 passed.
test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample: in the disabled branch, `ordered = [item[1] for item in scored]` became `ordered = list(pool)` (pool order, not similarity order). RED on all 5 params at line 139 `assert case["draws"] == case["expected"]`. Restored from .bak4, diff clean, GREEN 5 passed.
test_a_pool_of_limit_or_fewer_comes_back_whole: in _random_from_pool, the small-pool `return candidates` became `return candidates[1:]`. RED on both params at line 147 `assert sorted(draw) == sorted(SMALL[name])`: small_equal drew ['b','c','d','e'] and small_under drew ['b','c']. Restored from .bak5, diff clean, GREEN 2 passed.
Every mutation left the child running: no draws-fixture returncode failure, and only the named test went red. popular_videos.py ends cmp-identical to its pre-mutation copy, and no .bak remains under engine/ or client/.
</mutations>

<cleared>
delete_me/ holds 6 files:
- test_16_popular_weighted_random_phase1.py, which is the whole scope moved out of tests/tmp.
- popular_videos.py.bak1 to .bak5, the Step 6 restore copies. Each is byte-identical to the current production file.
tests/tmp holds none of the files in scope. It is not empty: the six probe_16_*.py files (popular_child, popular_harness, popular_margin, refactor_equivalence, reference_draw, zero_unused) were outside the scope I was given and stay there, as the plan said. Nothing was deleted; you decide what happens to delete_me/.
Closing run: I restored the preharvest snapshot over tests/last_test_validation.json, then ran --compare. It selected 2 of 28 groups, with 26 unchanged and carried from the record:
- test_popular_videos.py (no record): 11 passed.
- test_search_fusion.py (no map entry; this harvest did not touch it): 10 passed.
In total 21 passed, 0 failed. Delta against the pre-harvest record: 11 appeared, all tests.active.test_popular_videos items; 0 departed; no new red; nothing went from red to green. That matches the harvest: 5 tests (11 items) added, 0 retired.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: none

`--compare` exited 0.

```
selected 1 of 28 test groups (27 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.1s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

