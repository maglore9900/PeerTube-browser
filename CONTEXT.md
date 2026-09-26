# Glossary

- **Profile** — an optional per-visitor identity held by the Client backend, proved by an opaque key sent as `X-Profile-Key`. Likes kept server-side, dislikes and blocks belong to a profile.
- **Dislike** — a profile's soft negative signal on one video. The video is removed from that profile's feeds and videos similar to it are ranked lower; nothing changes for other visitors and no interaction event is published. A dislike and a like on the same video replace each other.
- **Taste vector** — one of up to four centroids the Engine computes from a profile's disliked videos' embeddings. The Client backend stores them and sends them with the profile's feed requests; the Engine penalises candidates close to them.
- **Block** — a profile's hard exclusion of a channel (`instance_domain` + `channel_id`) or an account (`account_url`) from its feeds and search results. Distinct from a dislike, which removes one video and down-ranks similar ones, and from the Engine's operator moderation, which applies to every visitor.
