---
name: skill-authoring
description: The standard a skill in this project is held to - header, length, structure, and what must never be invented. Read it before authoring one with SkillManage.
---
# Agent instructions:

## What a skill is

Instructions a later session loads on demand to do one task well. Not documentation, not a
tutorial. If a reader would not ACT on a line, cut it.

## The header

    ---
    name: <kebab-case, matching the directory>
    description: One sentence saying what it covers and when to reach for it.
    ---

`SkillManage` owns `name` and the author marker and overwrites both, so do not hand-craft
them. You own the description. Write it for someone deciding whether to open the file - it
is the only part that reaches every session, through the skill index in the system prompt.

## Length and structure

Under 200 lines. A skill needing more is two skills, or one skill plus a reference file
beside it that the body names - add that file with `write` and a `path`, after `create`.

Lead with what to do. Put reasoning underneath, and only where a reader would otherwise get
it wrong.

## Never invent

Every command, flag, path and file name must have been READ, not inferred. A skill is
durable input to sessions that cannot check it, so a plausible-looking wrong path costs more
than an absent one. Where you did not verify something, say so in the skill rather than
smoothing over it.
