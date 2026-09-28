# 16-popular-weighted-random

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/20-16-popular-weighted-random.record.md`._

## Requirements

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

## High-level plan

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

## Impacts


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


## Documentation to update

- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md "popular Layer": added `generators.popular.weighted_random_alpha` to the params list and replaced the incorrect Behavior sentence with a description of the similarity-weighted draw.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular entries in §3 and §4 now describe the similarity-weighted draw, and the §4 pool line applies caps before the draw.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Relabelled the popular pool node so it shows a similarity-weighted draw rather than a similarity ranking.
- [x] `docs/project/issues/16-popular-weighted-random.md` - updated: Issue 16 is marked `enhancement, complete` and copied to `docs/project/issues/archive/`, with a Delivered note. The original at `docs/project/issues/16-popular-weighted-random.md` still has to be deleted.
- [x] `docs/project/roadmap.md` - updated: Roadmap: added a Delivered entry for issue `16` (similarity-weighted popular draw) and removed `16` from the outstanding F3-M3 and Feed ordering lines.
- [x] `docs/project/issues/plan.md` - updated: Marked Wave 2 lane 2c (issue 16, popular weighted random) as delivered in `docs/project/issues/plan.md`.

## Implementation plan

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

### Phases

#### Phase 1 - Similarity-weighted popular draw [code]

**Files touched.** engine/server/api/recommendations/candidates/popular_videos.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_popular_weighted_random.py (NEW)

**Checkpoint.** Seam: the public `PopularVideosGenerator.get_candidates(server, user_id, limit, config=...)`. It is driven with stub `PopularVideosDeps`: a fixed pool that ignores `count`, one like `[1, 0]`, and 2-D vectors `[s, sqrt(1-s²)]` so each cosine is exactly `s`. The caps are 0 and the server is a `SimpleNamespace(db=None, db_lock=threading.Lock())`. Harness: `tests/active/test_popular_weighted_random.py` runs every case in one Engine-interpreter child (`ENGINE_PY -c _CHILD SERVER_DIR CASES_JSON`, `sys.path[:0] = [server, server + "/api"]`), which reseeds `random` per trial with a string seed and reports JSON. This follows the existing ENGINE_PY child precedent in `test_search_fusion.py` and `test_internal_client_reads.py`; that route is needed because the pytest interpreter lacks numpy. Asserts for clause_1: skew (10 hi at 0.9 vs 10 lo at 0.1, alpha 1, 400 trials): every draw has `limit` distinct ids, and hi hits ≥ 3 × lo hits. zero_fill (3 positive, 7 zero-weight including negative and missing-embedding, limit 5): all 3 positives are in every draw, and across trials the fill covers every zero-weight id. zero_unused (6 positive, 10 zero): no zero-weight id ever appears. Asserts for clause_2: all_zero and the five disabled configs (key missing, None, 0, -1.0, NaN) each equal `random.sample(ordered, limit)` recomputed under the same seed. In the disabled cases `popular_videos._weighted_from_pool` is replaced by a function that raises, so taking the wrong branch fails the fixture's return-code assert. Regression guard: pools of exactly `limit` and fewer than `limit` come back whole.

**Intent.** `PopularVideosGenerator.get_candidates` in `popular_videos.py` ends its likes path in a new `_weighted_from_pool` draw that favours candidates closer to the likes whenever `weighted_random_alpha` is positive (1.0 in the `home` and `upnext` profiles), and ends it in today's uniform `_random_from_pool` sample otherwise.

- C1 - With likes and a positive alpha, the popular layer returns `limit` distinct candidates in which closer candidates appear clearly more often, and zero-weight candidates appear only when there are too few positive-weight ones to fill `limit`.
- C2 - With a missing, None, zero, negative or NaN alpha, or with every weight zero, the popular layer's draw is exactly the uniform `random.sample(ordered, limit)` under the same seed.

**Outcome.** ### `engine/server/api/recommendations/candidates/popular_videos.py`
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


