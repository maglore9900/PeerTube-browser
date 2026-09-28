# Recommendation Delivery Pipeline Diagram

Below is a Mermaid diagram of the delivery pipeline, based on `engine/server/api/recommendations/docs/OVERVIEW.md`. The home feed runs the layer pipeline. Up-next, a seeded request, builds one similarity pool and draws its page from that pool. For the up-next parameters see `LAYER_PARAMS.md`.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 50, "rankSpacing": 50}, "themeVariables": {"fontSize": "48px"}}}%%
flowchart TD
    A[Request /recommendations] --> A1[Resolve likes source<br/>client JSON or users DB]
    A1 --> B{Seed video provided?}
    B -- no --> C[Mode: home<br/>Profile: home]
    B -- yes --> D[Mode: upnext<br/>Profile: upnext, or guest_upnext without likes<br/>also /videos/similar and GET /videos/id/similar]

    C --> E[RECOMMENDATION_PIPELINE config]

    E --> F[Data preparation]
    F --> F1[Video embeddings<br/>SentenceTransformer]
    F --> F2[ANN index on embeddings]
    F --> F3[Similarity cache<br/>video_id score rank<br/>refresh if score missing]

    E --> E0{Has likes?}
    E0 -- no --> E1[Use guest profile]
    E0 -- yes --> E2[Use home profile]

    E1 --> G[Candidate gathering by layer]
    E2 --> G
    G --> G1[exploit<br/>similar to likes]
    G --> G2[explore<br/>moderately similar]
    G --> G3[popular<br/>popularity + capped signal]
    G --> G4[random<br/>random cache]
    G --> G5[fresh<br/>recent videos]

    G1 --> H1[Exploit pool<br/>filter similarity >= exploit_min]
    G2 --> H2[Explore pool<br/>filter similarity_min..max]
    G3 --> H3[Popular pool<br/>similarity-weighted draw if likes]
    G4 --> H4[Random pool<br/>optional similarity < explore_min]
    G5 --> H5[Fresh pool<br/>recent + similarity_score]

    H1 --> Hcaps[Apply author/instance caps]
    H2 --> Hcaps
    H3 --> Hcaps
    H4 --> Hcaps
    H5 --> Hcaps

    Hcaps --> Hr[Random pick N]

    F3 --> S[Similarity candidates filters<br/>seed exclude<br/>error_threshold<br/>max_per_author<br/>exclude_source_author]
    S --> G1

    Hr --> I[Gather limits by profile<br/>batch_size * gather_ratio<br/>* overfetch_factor<br/>ratios normalized over active layers]

    I --> J[Unified scoring]
    J --> J1[score = w_sim*similarity<br/>+ w_fresh*freshness<br/>+ w_pop*popularity<br/>+ layer_bonus]
    J --> J2[Dislike penalty, if dislike_centroids<br/>score -= w_sim*cosine when cosine >= floor]

    J --> K[Layer mixing]
    K --> K1[Final quota<br/>batch_size * mix_ratio<br/>ratios normalized over active layers]
    K --> K2[Fallback: explore -> exploit -> popular -> random -> fresh]
    K --> K3[Penalised candidates<br/>after all others]

    K --> L[Post-filters]
    L --> L1[Deduplication]
    L --> L2[Layer soft-caps]

    L --> M[Response to client<br/>batch + seed mode]

    D --> U1[Similarity cache read<br/>never written<br/>skipped when refresh_cache]
    U1 --> U2[Pool filters<br/>tail floor 0.25<br/>seed, error, author caps<br/>request exclude<br/>moderation]
    U2 --> U3{Pool below TARGET_MIN_POOL<br/>or no cache entry?}
    U3 -- yes --> U4[ANN fallback steps<br/>nprobe 32 -> 128, k 5000 -> 20000<br/>hits >= 0.35, then tail >= 0.25<br/>nprobe restored under index_lock]
    U3 -- no --> U5
    U4 --> U5[Dedup by video_uuid+instance and like_key<br/>cap TOP_K 300]
    U5 --> U6[Unified scoring<br/>+ dislike penalty over the whole pool]
    U6 --> U7[Top-M window<br/>M = SAMPLE_WINDOW_FACTOR * limit]
    U7 --> U8[Likes rerank of the window<br/>alpha 0.7 / beta 0.3<br/>stamps personalized_score]
    U8 --> U9[Weighted draw of limit rows<br/>Efraimidis-Spirakis<br/>random, or reproducible with seed]
    U9 --> U10[Page sorted by draw weight<br/>upnext_pool log line]

```
