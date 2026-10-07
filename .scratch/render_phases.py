import json
import re

P = 'docs/project/plans/54-53-tags-on-cards-and-tag'
t = open(P + '.record.md').read()
s = t.index('```json') + 7
e = t.index('dev-flow:state -->', s)
e = t.rindex('}', s, e) + 1
r = json.loads(t[s:e])['replies']['step_6_develop_phase_breakdown']
out = []
for m in re.finditer(r'<phase n="(\d)" kind="(\w+)">(.*?)</phase>', r, re.S):
    n, k, b = m.groups()
    g = lambda tag: re.search(f'<{tag}>(.*?)</{tag}>', b, re.S).group(1).strip()
    out.append(f"#### Phase {n} — {g('name')}\n\n**Kind:** {k}\n\n**Intent:** {g('intent')}\n\n**Clauses:**\n\n- `C1` {g('clause_1')}\n")
    c2 = re.search(r'<clause_2>(.*?)</clause_2>', b, re.S)
    if c2:
        out.append(f"- `C2` {c2.group(1).strip()}\n")
    out.append(f"\n**Checkpoint and seam:** {g('checkpoint')}\n\n**Files:** {g('files')}\n\n**Self-check rows:** _pending (Step 7.2)._\n\n**Auditor verdicts:** _pending (Step 7.3)._\n\n**Changes:** _pending (Step 7.5)._\n\n**Checkpoint outcome:** _pending._\n\n")
nc = re.search(r'<needs_coordination>(.*?)</needs_coordination>', r, re.S).group(1).strip()
ra = re.search(r'<rationale>(.*?)</rationale>', r, re.S).group(1).strip()
out.append(f"#### Coordination\n\n{nc}\n\n#### Rationale for the split\n\n{ra} The `dev-flow` workflow refuses more than 4 phases outright, so on 2026-10-06 the operator approved the five phases again and directed the build to continue by hand under `workflows/dev_flow.md` from Step 7.\n")
w = open(P + '.md').read()
placeholder = "_Not yet written - Step 4 owns it._\n"
assert placeholder in w
w = w.replace(placeholder, ''.join(out))
old = "_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/54-53-tags-on-cards-and-tag.record.md`._"
assert old in w
w = w.replace(old, "_Steps 0-6 were run by the `dev-flow` workflow; their gate evidence is in `docs/project/plans/54-53-tags-on-cards-and-tag.record.md`. The workflow refuses a plan of more than 4 phases, so from Step 7 the build continues by hand under `workflows/dev_flow.md` and this file is edited directly._")
open(P + '.md', 'w').write(w)
print(sum(1 for x in out if x.startswith('#### Phase')))
