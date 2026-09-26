# Glossary

- **Profile** — an optional per-visitor identity held by the Client backend, proved by an opaque key sent as `X-Profile-Key`. Likes kept server-side and blocks belong to a profile.
- **Block** — a profile's hard exclusion of a channel (`instance_domain` + `channel_id`) or an account (`account_url`) from its feeds and search results. Distinct from a dislike, which only down-ranks similar videos, and from the Engine's operator moderation, which applies to every visitor.
