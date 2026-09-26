# Update the recommendation description (RECOMMENDATIONS_OVERVIEW)

Status: enhancement, needs-triage
Origin: task 16, [M8][F5]

## Problem

`RECOMMENDATIONS_OVERVIEW.md` does not match the current recommendation logic.

## Proposed solution

Rewrite the document to describe the whole pipeline:

- data preparation (embeddings, cache, index),
- candidate generation and layer mixing,
- filters, deduplication and mixing rules,
- what the client receives and how the frontend uses it.

## Related

- Best done after the similarity and feed issues (`09`, `16`, `17`) land, or it is rewritten twice.

## Comments
