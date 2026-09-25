# How to write a skill

A skill is task instructions the agent loads on demand. Its name and description sit in the system prompt every turn; its body is read only when the agent calls the `Skill` tool. Write one when instructions are long and needed occasionally. Write a [rule](how-to-write-a-rule.md) instead when the text is short and always relevant.

## The smallest working skill

Two steps: a directory with a `SKILL.md`, and a table in `.un/config.toml`.

```
.un/skills/
└── database-migrations/
    └── SKILL.md
```

```markdown
---
name: database-migrations
description: How to write and apply a schema migration in this project.
---

Migrations live in `db/migrations/`, numbered sequentially.

1. Copy the latest file and bump the number.
2. Write the `up` and the `down`.
3. Run `make migrate` before committing.
```

```toml
[skills.database-migrations]
enable = true
```

The heading is the DIRECTORY name, not the frontmatter `name`. A skill with no table, or a table without `enable`, is off.

Discovery runs on every `Skill` call, so a skill you add or edit mid-session is picked up without a restart.

## Writing the description

The description is the only part that reaches every session. Write it for someone deciding whether to open the file: what it covers, and when to reach for it.

```yaml
description: Deploying to staging - the flag order, the smoke check, and how to roll back.
```

Not `description: Deployment stuff.`

## Writing the body

Lead with what to do. Put reasoning underneath, and only where a reader would otherwise get it wrong. If a reader would not act on a line, cut it.

Keep it under about 200 lines. A skill needing more is two skills, or one skill plus a supporting file beside it that the body names:

```
.un/skills/database-migrations/
├── SKILL.md
└── rollback-checklist.md
```

The body has to name the supporting file, or nothing will read it.

Every command, flag and path in a skill must be one you checked. A later session cannot verify what you wrote, so a plausible wrong path costs more than an absent one.

## When frontmatter is broken

A skill that will not parse is not dropped. It appears in the index flagged with its error, and the session still starts:

```
- release-checklist: (unreadable - unparseable frontmatter: ScannerError)
```

Two failures are recorded: YAML that will not parse, and frontmatter that parses to something other than a mapping.

## Skills the agent writes

The agent can author skills through the `SkillManage` tool. It stamps `metadata: {author: agent}` into the frontmatter and refuses to amend any skill that does not carry that marker, so your skills are safe from it.

Authoring and enabling are separate. `SkillManage create` writes a skill and leaves it off; only you turn it on.

## Curation

With `[self_learning.curate.skills]` configured, un retires agent-written skills nobody has read for `retire_after_days` (default 30). Retiring moves the skill's whole directory to `.un/learning/archive/skills/<name>/` and logs a row in `.un/learning/retirements.jsonl` saying where it went and why. After that `discover` does not walk it, the `Skill` tool does not find it, and no read brings it back. Its record of reads lives in `.un/learning/skill-curator.json`, never in your `SKILL.md`.

What saves a skill is being READ. Every `Skill` read moves its stamp forward, and the pass measures from the newest stamp — so a skill in genuine use never ages out. A skill un has just met is seeded on one pass and judged only by a later one, so it always gets at least its full grace window.

Nothing is deleted, and the archive is never overwritten: retire a name twice and the second copy lands beside the first as `<name>-2`. Undoing a retirement is a `mv` out of the archive; the log row tells you which directory to move.

The `Retire` tool is the other route, and it is for a different question. It records that a skill's content now lives somewhere else — `promoted` into a skill, or `merged` into another skill — which is a judgement no clock can make. It cannot retire anything by age; that is the pass's job.

Your own skills are never touched by either: the pass and the tool both exempt anything without the agent marker. To pin an agent-written skill, add to its frontmatter:

```yaml
metadata:
  pinned: true
```

## Why the index matters

Every enabled skill's description is in the prompt on every turn, for as long as the skill exists. A collection nobody prunes costs more prompt each time it grows. Delete or disable skills you no longer use.
