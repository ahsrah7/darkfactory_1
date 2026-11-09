---
name: jira-transition
description: "Use when: moving a Jira ticket to its next status after an agent's outcome is known, or deciding whether a ticket may leave its current status."
---

# Jira transition

The source of truth is [state-machine.json](../../factory/state-machine.json). Follow [tracker-state-machine](../tracker-state-machine/SKILL.md) for the rules on each state. Calls go through the [jira-api](../jira-api/SKILL.md) client.

## Scripts

```powershell
python .github/skills/jira-transition/scripts/next_transition.py "Ready for Dev" onSuccess           # offline: prints the target status
python .github/skills/jira-transition/scripts/apply_transition.py SCRUM-7 onSuccess --dry-run    # checks the Jira move, makes no change
python .github/skills/jira-transition/scripts/apply_transition.py SCRUM-7 onSuccess               # makes the move
```

`apply_transition.py` exit codes:

- `0`: moved, or dry run.
- `1`: Jira or config error.
- `2`: no single Jira transition from the current status to the target.
- `3`: refused by the state machine. The target is Done, or the ticket is Blocked.
- `4`: the status after the move does not match the target.

## Procedure

1. Read the current status with `read_issue.py KEY` ([jira-read-status](../jira-read-status/SKILL.md)).
2. Find the target with `next_transition.py CURRENT OUTCOME`. Exit 2 means set Blocked. Exit 3 means stop.
3. Write the comment first with [jira-comment](../jira-comment/SKILL.md). It names the target status and the evidence.
4. Run `apply_transition.py KEY OUTCOME --dry-run`, then run it again without the flag.
5. On exit 4 or any other failure, comment and set Blocked.

## Rules

- Never skip a state. The move uses the Jira transition that leads to the state machine's target.
- Never move a ticket out of Blocked. Only a human does that.
- Never move a ticket to Done, and never merge a pull request. Those belong to the pr-gate and test runner.
- A transition under a human gate (auth, infrastructure, migrations, secrets, or production deploy in `humanGates`) needs recorded human approval first.
- Never create or rename statuses.
