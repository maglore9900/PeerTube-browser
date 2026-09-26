# Search API: multilingual hybrid video search

Status: delivered. Migrated from the retired `dev/FEATURE_PLANS.md` (feature `F6-M3`, milestone M3, old tasks 87-91). Built before the switch to devsecops, so there is no dev_flow build record; the operator accepted it as delivered at migration.

## Requirements

### What was asked

There was no video search of any kind. The Engine served similarity, recommendation and channel-listing routes; a free-text video query had no endpoint and no index. Add both retrieval halves — an FTS5 lexical index over the metadata the dataset holds, and a vector half over the existing FAISS index — fused behind one read endpoint.

### Purpose

Cross-language retrieval. BM25 only matches tokens the query and the document share, so an English query cannot reach a Russian video; a multilingual embedding space can. The planning premise that the corpus is "mostly non-English" was later measured wrong: 3.7% of titles carry Cyrillic and 58.8% are ASCII-only (890,052 rows).

### Scope

- **S1 Multilingual embedding space.** `build-video-embeddings.py` defaults to `paraphrase-multilingual-MiniLM-L12-v2`; `run-dataset-build.sh` passes the model explicitly; `DATA_BUILD.md` corrected.
- **S2 FTS5 index.** External-content `videos_fts` over `title`, `description`, `tags_json`, `category`, `channel_name`, created in `ensure_content_schema` and built in the existing `sync` stage.
- **S3 Index consistency under every writer.** Insert/update/delete triggers on `videos` (the updater merge writes outside sync); `whitelist_migrations.py` drops and rebuilds the FTS table around its drop/rename of `videos`.
- **S4 Query encoder lifecycle.** One `SentenceTransformer`, loaded lazily behind a lock, released after an idle timeout.
- **S5 Model identity gate.** The configured query-encoder model must equal the index's recorded model, or the vector half is disabled (not the process).
- **S6 Endpoint.** `GET /api/v1/search/videos?q=&page=&limit=&sort=`, stable video row shape plus `total` and `generatedAt`; `sort=relevance` fused, `published_at`/`views`/`popularity` lexical-only; `limit` clamped.
- **S7 Query sanitisation.** Tokenise, drop FTS5 operators, quote each token, cap token count and length; one sanitizer for both halves.
- **S8 Parity.** Serving moderation filters, per-path rate limit, statement deadline; encoding outside `db_lock`.
- **S9 Gateway exposure** in `PROXY_READ_GET_ROUTES` and `PROXY_ALLOWED_QUERY_PARAMS`.

### Out of scope

Translation and subtitles; storing `language` on `videos`; reranking beyond RRF; the search page (archive 02); widening the corpus; channel search; personalised results.

### Acceptance criteria

1. After a `sync` run, `COUNT(*)` of `videos_fts` equals that of `videos`.
2. Insert/update/delete on `videos` outside sync keeps the counts equal and the text findable or unfindable accordingly.
3. The endpoint returns matching rows in the stable row shape with `total` and `generatedAt`.
4. An English query returns relevant non-English videos sharing no token with it (manual, live dataset).
5. An exact title, tag or channel name still ranks first.
6. `page`/`limit` page without repeats or skips; `limit` over the cap is clamped.
7. Each `sort` orders by its field; `relevance` by the fused ranking.
8. FTS5 operator strings return normal or empty results, never a 500 or an unbounded scan.
9. Many tokens or one very long token are capped and answer within the statement deadline.
10. Concurrent first searches load the encoder once.
11. After the idle timeout the model is released and the next search reloads correctly.
12. A model mismatch disables vector results and logs both names.
13. Moderated videos do not appear.
14. Reachable through the gateway; an unlisted parameter is rejected there.
15. `tests/check-client-engine-boundary.sh` and `tests/check-frontend-client-gateway.sh` pass.

## High-level plan

### Resolved decisions

- **O1 — hybrid**, reversing an earlier BM25-only decision: the Engine environment already ships `torch` and `sentence_transformers`, and cross-language retrieval needs vectors. BM25 stays because it wins on exact titles, tags, channel names and proper nouns.
- **O2 — model `paraphrase-multilingual-MiniLM-L12-v2` (384-dim)** over `multilingual-e5-base`: same dimension as before (~1.37GB vs ~2.7GB for 892k rows) and no query/passage prefix protocol. A one-way door: reversing it costs a full re-embed.
- **O3 — lazy load, resident while used, idle release** (`QUERY_ENCODER_IDLE_SECONDS`, default 900). The import (4.2s) is the expensive part and is paid once; a reload after eviction costs only the 0.13s load.
- **O4 — eviction by a daemon timer thread; the getter hands out a strong reference under the lock**, so an eviction mid-encode cannot fault a request thread.
- **O5 — fusion by reciprocal rank (k=60)**, not by score: bm25 and cosine are not comparable without re-tuned normalisation.
- **O6 — encode on CPU**: 5ms warm; the GPU is wanted by the batch re-embed.
- **O7 — external-content FTS**: no second copy of the text; consistency is the triggers' job.
- **O8 — FTS built in the `sync` stage**, not a new one.
- **O9 — the route is born versioned** at `/api/v1/search/videos`; the other routes stay unversioned until roadmap `F2-M3`.

### Risks carried forward

- **Model/index mismatch is invisible to a dimension check** (both models are 384-dim). `data/embedding_space.py` is the single identity gate, used by `api/server.py`, `build-ann-index.py` and `precompute-similar-ann.py`.
- **FTS5 defaults to AND.** `sanitize_query` OR-joins tokens; reverting that makes every multi-word query return nothing.
- **RRF favours same-language results**: a row found by both halves scores about twice a vector-only row, and lexical hits are same-language by construction.
- **`max_seq_length` is 128** (old model 512), so ~15.4% of payloads truncate and `build_text()` puts tags/category/channel last. Accepted; FTS5 still indexes those fields.
- **Encoding under `db_lock` would stall every read route**; it must stay outside.
- **Serving memory**: ~605MB RSS with the model loaded, on top of the mmapped FAISS index.

## Impacts

Not recorded: built outside dev_flow. Files touched are in commit `45180d6` (`engine/server/data/{search,query_encoder,db}.py`, `engine/server/api/{server,server_config}.py`, `engine/server/api/handlers/similar.py`, `engine/server/db/jobs/{build-video-embeddings,sync-whitelist,whitelist_migrations}.py`, `scripts/run-dataset-build.sh`, `scripts/run-reembed.sh`, `client/backend/server.py`, `DATA_BUILD.md`).

## Implementation plan

Not recorded: built outside dev_flow as old tasks 87 (model), 88 (FTS5), 89 (encoder), 90 (endpoint), 91 (gateway).

## Inner unit tests

None under devsecops. Durable checks from before the switch are the shell harnesses in `tests/` and `engine/server/db/jobs/tests/`; none are in `tests/active`.

## Close

Delivered in commit `45180d6`, re-embed and dataset rebuild run on the live dataset. Clause accounting and `--compare` do not apply: no dev_flow build. Which acceptance criteria were verified before migration is not recorded.
