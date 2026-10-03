import re, pathlib
src = pathlib.Path("docs/project/plans/19-17-stable-ann-ids.md").read_text().splitlines(keepends=True)
text = "".join(src)
impacts = re.findall(r'(<impact path="([^"]+)".*?</impact>)', text, re.S)
A = {"engine/server/data/ann_ids.py","engine/server/data/moderation.py","engine/server/db/jobs/whitelist_migrations.py",
     "engine/server/db/jobs/migrate-whitelist.py","engine/server/db/jobs/build-video-embeddings.py","engine/server/db/jobs/sync-whitelist.py",
     "engine/server/db/jobs/merge-staging-db.py","engine/server/db/jobs/merge_rules.json","engine/server/db/jobs/updater-worker.py",
     "engine/server/data/videos.py","engine/server/db/jobs/tests/test-orchestrator-smoke.py","engine/server/db/jobs/tests/test-moderation-integration.py",
     "tests/active/conftest.py","tests/active/test_video.py","tests/active/test_whitelist_migrations.py","tests/config.json","scripts/run-dataset-build.sh"}
B = {"engine/server/db/jobs/build-ann-index.py","engine/server/data/embedding_space.py","engine/server/api/server.py","engine/server/data/embeddings.py",
     "engine/server/data/ann.py","engine/server/data/metadata.py","engine/server/data/search.py","engine/server/api/handlers/similar.py",
     "engine/server/data/random_cache.py","engine/server/data/random_videos.py","engine/server/db/jobs/precompute-random-rowids.py",
     "engine/server/api/server_config.py","engine/server/db/jobs/precompute-similar-ann.py","engine/server/db/jobs/inspect-embedding.py",
     "engine/server/db/jobs/instance-denylist-cli.py","engine/server/data/moderation.py","engine/server/data/similarity_candidates.py",
     "engine/server/api/handlers/internal_client_reads.py","engine/server/api/recommendations/sources/ann_similar_from_likes.py",
     "engine/server/db/jobs/tests/test-orchestrator-smoke.py","tests/active/conftest.py","tests/active/test_metadata.py",
     "tests/active/test_random_videos.py","tests/active/test_random_cache.py","tests/active/test_db.py","tests/active/test_precompute_random_rowids.py",
     "tests/active/test_precompute_similar_ann.py","tests/active/test_video.py","tests/active/test_similarity_candidates.py","tests/active/test_search.py",
     "tests/active/test_blocks.py","tests/config.json","scripts/run-reembed.sh","tests/archive/random_cache_in_place/test_random_cache.py"}
paths = [p for _, p in impacts]
skipped = [p for p in paths if p not in A and p not in B]
print("unassigned:", skipped)
def lines(a, b):  # 1-based inclusive
    return "".join(src[a-1:b])
draft = {n: None for n in range(1, 16)}
starts = [i+1 for i, l in enumerate(src) if re.match(r"### \d+\. ", l)]
ends = starts[1:] + [next(i+1 for i, l in enumerate(src) if l.startswith("### Seams"))]
for s, e in zip(starts, ends):
    n = int(re.match(r"### (\d+)\.", src[s-1]).group(1))
    draft[n] = lines(s, e-1)
def build(head, keep, nums, tail, out):
    imp = "\n".join(body for body, p in impacts if p in keep)
    body = head + "## Impacts\n\n_Carried from build 19's Step 3-4 inventory (line numbers as of that tree). Entries that span both plans are carried whole; the part outside this plan is for context._\n\n<impacts>\n" + imp + "\n</impacts>\n\n"
    body += tail
    body += "## Draft implementation carried from build 19 (Step 5)\n\n_The settled draft, sections for this plan only, numbered as in build 19. This build's Step 5 re-drafts against the tree; where the two differ, the tree wins._\n\n"
    body += "".join(draft[n] for n in nums)
    pathlib.Path(out).write_text(body.rstrip() + "\n")
    print(out, len(body.splitlines()))
d = pathlib.Path(".scratch/ann-split")
build((d/"a_head.md").read_text(), A, [1,2,3,4,5,6,7,13,14], (d/"a_docs.md").read_text(), "docs/project/plans/41-ann-ids-a-schema-writers.md")
build((d/"b_head.md").read_text(), B, [8,9,10,11,12,13,14], (d/"b_docs.md").read_text(), "docs/project/plans/42-ann-ids-b-readers-cutover.md")
