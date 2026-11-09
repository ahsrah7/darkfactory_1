---
name: jira-status-check
description: "Use when: verifying that every state name in state-machine.json exists as a Jira status, after a Jira workflow change, or before the factory starts a run."
---

# Jira status check

This is the Jira side of the state-machine check. It compares every state name in [state-machine.json](../../factory/state-machine.json) with the project's statuses, through the [jira-api](../jira-api/SKILL.md) client.

## Scripts

```powershell
python .github/skills/jira-status-check/scripts/check_statuses.py              # live: the project's statuses from Jira
python .github/skills/jira-status-check/scripts/check_statuses.py saved.json   # offline: a saved statuses response
```

Exit codes: 0 all names exist, 1 names are missing (they are listed), 2 a Jira or config error.

## Procedure

1. Run the live check before the first transition of a run, and after any workflow edit.
2. If any name is missing, stop the run and set Blocked for a human. Do not create or rename statuses. That is a human workflow change.

## Rules

- The comparison is case-sensitive.
- The script reads the runner's Jira variables itself. Agents run it and do not pass or copy those values.
