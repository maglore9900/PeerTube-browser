# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Read these before exploring

- **`CONTEXT.md`** at the repo root: the glossary. Every domain term the project uses is defined here.
- **`docs/project/adr/`**: one architecture decision per file. Read the ADRs touching the area you are about to work in.
- **`docs/project/roadmap.md`**: milestones, unplanned roadmap features, what has been delivered, and the cross-feature implementation order.

Where one of these does not exist yet or is empty, proceed without it and do not stop to scaffold it. They get created when a term or a decision actually needs recording, not upfront.

## File structure

```
/
├── CONTEXT.md
└── docs/
    └── project/
        ├── adr/                  ← one decision per file, NNNN-<slug>.md
        ├── issues/               ← see issue-tracker.md
        ├── plans/
        │   └── archive/          ← completed plans, and ones the user declined
        ├── domain.md
        ├── issue-tracker.md
        ├── roadmap.md
        └── triage-labels.md
```

## Use the glossary's vocabulary

When your output names a domain concept — an issue title, a refactor proposal, a hypothesis, a test name — use the term as `CONTEXT.md` defines it. Do not drift to synonyms the glossary avoids.

A concept missing from the glossary is a signal: either you are inventing language the project does not use, which is a reason to reconsider, or there is a real gap worth naming.

## Flag ADR conflicts

Where your output contradicts an existing ADR, surface it rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
