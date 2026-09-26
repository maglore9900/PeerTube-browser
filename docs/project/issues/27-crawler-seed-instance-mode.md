# Crawler mode: start from one instance and its subscriptions

Status: enhancement, needs-triage
Origin: task 15, [M4][F3] (roadmap feature F2-M4 "crawler mode with federated scope limitation" is the closer match)

## Problem

There is no crawler mode that starts from one instance and walks its federated subscriptions.

## Proposed solution

A mode taking a seed instance domain, in which the crawler:

1. finds all instances it follows,
2. collects all channels from that instance and its federated instances,
3. collects all videos from those channels.

- CLI parameter for the seed domain (e.g. `--seed-instance`).
- Aligned with the existing instance crawler flags.

## Comments
