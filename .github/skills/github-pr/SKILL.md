---
name: github-pr
description: "Use when: committing and pushing a factory branch, opening or updating a pull request, reading PR state, posting a review decision, or enabling auto-merge. Scripts use GITHUB_TOKEN from the runner environment."
---

# GitHub PR scripts

Scripts for the factory's pull request loop. Run them from the repo root with `execute`. They use only the Python standard library.

Auth: `GITHUB_TOKEN`, then `GH_TOKEN`, then (Windows) the user-scope `GITHUB_TOKEN`. Scripts never print, log or store the token. Repo: `GITHUB_REPOSITORY`, else the `origin` remote.

## Commands

| Script | Use | Example |
|---|---|---|
| publish_branch.py | Commit and push only the given paths | `python .github/skills/github-pr/scripts/publish_branch.py --branch <branch> --scope products/<app> --message "<KEY>: <summary>"` |
| open_pr.py | Open the PR, or update the open one | `python .github/skills/github-pr/scripts/open_pr.py --head <branch> --title "<KEY>: <summary>" --body-file <file>` |
| pr_state.py | Read merge state, checks, status, rework rounds (read-only) | `python .github/skills/github-pr/scripts/pr_state.py --pr 12` |
| pr_feedback.py | Read the newest request-changes comment and inline comments (read-only) | `python .github/skills/github-pr/scripts/pr_feedback.py --pr 12` |
| review_pr.py | Post a review decision | `python .github/skills/github-pr/scripts/review_pr.py --pr 12 --decision approve --body-file <file>` |

Add `--dry-run` to publish_branch.py, open_pr.py or review_pr.py to preview without writes.

## Review decisions (plan_review)

- request-changes below the limit: review comment with the request-changes marker, status `factory/review` = failure.
- request-changes or approve at the limit (3 prior rounds): escalation comment, status failure. Not auto-merged, even when approved. A human decides.
- approve below the limit: review comment, status success. Squash auto-merge is enabled only when base branch protection requires `factory/review`. Otherwise the action is `automerge:skipped-no-protection`. If GitHub does not enable auto-merge, the action is `automerge:not-enabled` and the script exits 1.

## Rules

- Agents never merge a pull request directly. Auto-merge is set only by review_pr.py, and only on approval.
- Agents never use `--force` or `--force-with-lease`. publish_branch.py never pushes forcefully.
- GitHub forbids approving your own pull request, so the review is a PR comment plus the commit status `factory/review`.
- Rework limit: 3 request-changes rounds. Then the script escalates and a human decides.
- publish_branch.py refuses `main`, `master`, `origin/*`, absolute scopes and scopes containing `..`. It exits 3 when a staged path is outside the scopes.
- Protected paths (`auth/`, `infra/`, `migrations/`, `secrets/`, `products/*/migrations/`, `products/*/prisma/`) get the same review and auto-merge as other code. Production deploys still need a human.

## Exit codes

0 done (or dry run, or nothing to publish); 1 GitHub or git error; 2 refused input; 3 staged path outside scope.

## Tests

`python -m unittest discover -s .github/skills/github-pr/scripts -p "test_*.py" -v`
