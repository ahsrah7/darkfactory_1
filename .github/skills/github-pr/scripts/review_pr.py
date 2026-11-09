"""Record a review decision on a pull request.

Usage: review_pr.py --pr N --decision approve|request-changes --body-file FILE [--max-rework 3] [--dry-run]

Posts the review comment, sets the factory/review commit status and, on approval,
enables squash auto-merge only when the base branch protection requires factory/review.
Exit codes: 0 done or dry run; 1 GitHub error; 2 refused input.
"""

import argparse
import sys
from urllib.parse import quote

from gh_client import (
    STATUS_CONTEXT,
    GhError,
    configure_output,
    count_request_changes,
    graphql,
    repo,
    request,
    request_all,
)

DECISIONS = ("approve", "request-changes")
DEFAULT_MAX_REWORK = 3
STATUS_DESCRIPTION_LIMIT = 140
MARKERS = {
    "approve": "<!-- factory-review:approve -->",
    "request-changes": "<!-- factory-review:request-changes -->",
    "escalate": "<!-- factory-review:escalate -->",
}

PR_ID_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { id }
  }
}
"""

AUTO_MERGE_MUTATION = """
mutation($id: ID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH}) {
    pullRequest { autoMergeRequest { enabledAt } }
  }
}
"""


def plan_review(decision, prior_rework_rounds, base_requires_status, max_rework):
    """Return the ordered actions for a review decision. Pure: no I/O."""
    if decision == "request-changes":
        if prior_rework_rounds >= max_rework:
            return ["comment:escalate", "status:failure"]
        return ["comment:request-changes", "status:failure"]
    if decision == "approve":
        actions = ["comment:approve", "status:success"]
        if base_requires_status:
            actions.append("automerge:enable")
        else:
            actions.append("automerge:skipped-no-protection")
        return actions
    raise ValueError(f"unknown decision: {decision}")


def protection_requires_status(protection):
    """True when branch protection lists STATUS_CONTEXT as a required check."""
    checks = (protection or {}).get("required_status_checks") or {}
    contexts = list(checks.get("contexts") or [])
    contexts += [check.get("context") for check in checks.get("checks") or [] if isinstance(check, dict)]
    return STATUS_CONTEXT in contexts


def comment_kind(actions):
    for action in actions:
        if action.startswith("comment:"):
            return action.split(":", 1)[1]
    raise ValueError("plan has no comment action")


def status_description(kind, prior_rework_rounds, max_rework):
    if kind == "approve":
        text = "Approved by factory reviewer"
    elif kind == "escalate":
        text = "Rework limit reached; human decision needed"
    else:
        text = f"Changes requested (round {prior_rework_rounds + 1} of {max_rework})"
    return text[:STATUS_DESCRIPTION_LIMIT]


def build_comment(kind, body, prior_rework_rounds, max_rework):
    """Prepend the marker as the first line. Escalations also say that a human must decide."""
    if kind == "escalate":
        note = (
            f"Rework limit reached after {prior_rework_rounds} request-changes rounds "
            f"(limit {max_rework}). A human must decide. This pull request is not auto-merged."
        )
        return f"{MARKERS[kind]}\n{note}\n\n{body}"
    return f"{MARKERS[kind]}\n{body}"


def base_requires_status(owner, name, base):
    try:
        protection = request("GET", f"/repos/{owner}/{name}/branches/{quote(base, safe='/')}/protection")
    except GhError as exc:
        if exc.status == 404:
            return False
        raise
    return protection_requires_status(protection)


def enable_auto_merge(owner, name, number):
    data = graphql(PR_ID_QUERY, {"owner": owner, "name": name, "number": number})
    pull_request = (data.get("repository") or {}).get("pullRequest")
    if not pull_request:
        raise GhError(f"Pull request #{number} not found for auto-merge.")
    result = graphql(AUTO_MERGE_MUTATION, {"id": pull_request["id"]})
    enabled = result["enablePullRequestAutoMerge"]["pullRequest"]["autoMergeRequest"]
    if enabled is None:
        print("warning: GitHub did not report auto-merge as enabled", file=sys.stderr)
    return enabled


def _read_body(path):
    with open(path, encoding="utf-8-sig") as handle:
        body = handle.read().rstrip()
    if not body:
        raise ValueError("review body is empty")
    return body


def _execute(args, body):
    owner, name = repo()
    pr = request("GET", f"/repos/{owner}/{name}/pulls/{args.pr}")
    head_sha = pr["head"]["sha"]
    base = pr["base"]["ref"]
    is_open = pr["state"] == "open"
    if not is_open and not args.dry_run:
        print(f"refused: #{args.pr} is {pr['state']}, not open", file=sys.stderr)
        return 2
    comments = request_all(f"/repos/{owner}/{name}/issues/{args.pr}/comments")
    prior = count_request_changes(comments)
    requires_status = base_requires_status(owner, name, base)

    actions = plan_review(args.decision, prior, requires_status, args.max_rework)
    kind = comment_kind(actions)
    comment = build_comment(kind, body, prior, args.max_rework)
    state = "failure" if "status:failure" in actions else "success"
    description = status_description(kind, prior, args.max_rework)

    if args.dry_run:
        if not is_open:
            print(f"warning: #{args.pr} is {pr['state']}; a real run would refuse it")
        print("actions:")
        for action in actions:
            print(f"  {action}")
        print(f"status: context={STATUS_CONTEXT} state={state} description={description!r}")
        print(f"target_url: {pr['html_url']}")
        print("comment body:")
        print(comment)
        print("dry run: no writes made")
        return 0

    # The status goes first: if a later call fails, the PR never shows a comment without its status.
    request(
        "POST",
        f"/repos/{owner}/{name}/statuses/{head_sha}",
        {
            "state": state,
            "context": STATUS_CONTEXT,
            "description": description,
            "target_url": pr["html_url"],
        },
    )
    request("POST", f"/repos/{owner}/{name}/issues/{args.pr}/comments", {"body": comment})
    if "automerge:enable" in actions:
        enable_auto_merge(owner, name, args.pr)

    print("actions:")
    for action in actions:
        print(f"  {action}")
    return 0


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Record a review decision on a pull request.")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--decision", choices=DECISIONS, required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--max-rework", type=int, default=DEFAULT_MAX_REWORK)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.max_rework < 1:
        print("refused: --max-rework must be at least 1", file=sys.stderr)
        return 2
    try:
        body = _read_body(args.body_file)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    try:
        return _execute(args, body)
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
