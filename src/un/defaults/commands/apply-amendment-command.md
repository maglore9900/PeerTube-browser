---
description: Apply one amendment plan from .un/learning/amendments/ - the amendment-applier agent inserts its clause into the target file, retires the source memory and archives the plan; skill-auditor then audits a target under .un/skills/.
---

**Argument:** one plan under `.un/learning/amendments/` - its path, or its file name with or without `.md`. Empty lists the plans waiting and stops.

Apply the amendment plan named below. The operator naming it is the decision; your part is to dispatch the applier and relay what it did.

Plan:

$ARGUMENTS

In this order:

1. **Resolve the plan.** `Glob` `.un/learning/amendments/*.md`. The argument names a plan when it is the path of one of those files, or its file name with or without `.md`. When the argument is empty or names none of them, list the plans found one per line (or say there are none) and stop; the operator picks the plan.
2. **Dispatch the applier** with the plan's path, relative to the project root. Task's list of subagents leaves out `amendment-applier` and may say there is nothing to delegate to; dispatch it by that name all the same. The applier makes the edit and the `Retire` call, so this session makes neither.

   ```
   Task(subagent_type="amendment-applier", description="Apply one amendment plan",
        prompt=".un/learning/amendments/<plan>.md")
   ```

   When Task returns a line starting `refused:`, report it verbatim and stop. When the applier's `outcome:` is `stopped`, report its `reason:` and stop.
3. **Audit a skill target.** When the applier's `target:` path is under `.un/skills/`, dispatch `skill-auditor` over it. When that dispatch is refused or no such agent exists, report `skill-auditor not run:` and the reason in one line, and carry on.

   ```
   Task(subagent_type="skill-auditor", description="Audit an amended skill file",
        prompt="Audit <target>; an amendment just inserted a clause under <section>.")
   ```

4. **Report** the outcome, the target and section, the mirror, the memory's archived path, the plan's archived path, the applier's reason when it gave one, and the audit's findings. A mirror under `.un/skills/` is not audited; say so and name it, so the operator can run `skill-auditor` on it.

```
Usage: /apply-amendment
Usage: /apply-amendment do-not-softwrap-text--AGENTS
Usage: /apply-amendment .un/learning/amendments/do-not-softwrap-text--AGENTS.md
```
