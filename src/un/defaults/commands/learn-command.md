---
description: Author a skill from sources you name - a directory, a file, a URL, or this conversation.
---

Author a skill capturing what the sources below teach, so a later session can use it
without working it out again.

Sources:

$ARGUMENTS

In this order:

1. Read the `skill-authoring` skill with the `Skill` tool. It is the standard this project
   holds skills to. If it reports there is no such skill, say so in one line and carry on -
   `SkillManage` still enforces the header, and an existing skill under `.un/skills/` serves
   as the example.
2. Gather the sources with `Read`, `Grep`, `Glob` and `Bash`. Read them. Do not write about
   a file you have not opened.
3. Author it with `SkillManage` `create`.
4. Report the skill's name, its description, and what it deliberately does not cover.
