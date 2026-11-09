---
name: jira-comment
description: "Use when: posting an agent's outcome, evidence link or blocker as a Jira comment, or editing an existing agent comment in the dark factory."
---

# Jira comment

Every transition writes a tracker comment with links to its evidence ([AGENTS.md](../../AGENTS.md)). Posting goes through the [jira-api](../jira-api/SKILL.md) client.

## Scripts

```powershell
python .github/skills/jira-comment/scripts/build_comment.py --issue SCRUM-7 --agent software-developer --from-status "Ready for Dev" --to-status "In Review" --reason "PR opened." --evidence "pull request=<url>" --next "pr-reviewer picks up the ticket"
python .github/skills/jira-comment/scripts/build_comment.py --issue SCRUM-7 --comment-id 10500 --agent software-developer --from-status "Ready for Dev" --to-status "Ready for Dev" --reason "Corrected link."
python .github/skills/jira-comment/scripts/build_comment.py --agent architect --from-status "Design" --to-status "Ready for Dev"   # no --issue: prints the body only
```

Exit codes: 0 posted or printed, 1 bad arguments or credential in the text (nothing posted), 2 Jira error. The client checks every comment body before it sends anything.

## Procedure

1. Read existing comments with `read_issue.py KEY --comments` ([jira-read-status](../jira-read-status/SKILL.md)). Do not repeat a comment that says the same thing.
2. Post with `build_comment.py --issue KEY`. Use `--comment-id` only to correct a comment your own agent wrote.
3. Use this format: agent and mode; status moved from and to, or "Status unchanged" with the reason; evidence links; what a human must do next.

## Rules

- Comments are plain text in the REST v2 API. The script builds them, so no ADF is needed.
- Never include a credential, token or key in a comment. The client refuses to post text that looks like one, and nothing is sent.
- Never post in another agent's name, and never replace another agent's comment.
- Link evidence instead of pasting long logs.
