# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps each role to the label string this repo's issue tracker actually uses.

| Role              | Label in this tracker | Meaning                                  |
| ----------------- | --------------------- | ---------------------------------------- |
| `needs-triage`    | `needs-triage`        | Maintainer needs to evaluate this issue  |
| `needs-info`      | `needs-info`          | Waiting on reporter for more information |
| `ready-for-agent` | `ready-for-agent`     | Fully specified, ready for an AFK agent  |
| `ready-for-human` | `ready-for-human`     | Requires human implementation            |
| `wontfix`         | `wontfix`             | Will not be actioned                     |

Category roles are `bug` and `enhancement`, written as-is.

When a skill names a role — "apply the AFK-ready triage label" — use the label string from the middle column.

**The label is a `Status:` line near the top of the issue file**, carrying one category and one state, e.g. `Status: bug, needs-triage`. Issues are markdown in this repo, so a role is set by editing that line and read by looking at it.

Edit the middle column to match whatever vocabulary you actually use. Changing a string means editing the open issue files that carry it, since nothing migrates them for you.
