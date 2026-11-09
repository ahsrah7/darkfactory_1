"""Record a review decision on a pull request.

Usage: review_pr.py --pr N --decision approve|request-changes --body-file FILE [--max-rework 3] [--dry-run]

Posts the review comment, sets the factory/review commit status and, on approval,
enables squash auto-merge only when the base branch requires factory/review. The requirement is
read from both classic branch protection and the effective rules of the base branch (rulesets).
At or above the rework limit nothing is auto-merged: the decision escalates.
Exit codes: 0 done or dry run; 1 GitHub error, or auto-merge was not enabled after an approval
(reported as automerge:not-enabled); 2 refused input.
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
    """Return the ordered actions for a review decision. Pure: no I/O.

    At or above the rework limit the PR is never auto-merged: both decisions escalate.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    if prior_rework_rounds >= max_rework:
        return ["comment:escalate", "status:failure"]
    if decision == "request-changes":
        return ["comment:request-changes", "status:failure"]
    actions = ["comment:approve", "status:success"]
    if base_requires_status:
        actions.append("automerge:enable")
    else:
        actions.append("automerge:skipped-no-protection")
    return actions


def protection_requires_status(protection):
    """True when classic branch protection lists STATUS_CONTEXT as a required check."""
    checks = (protection or {}).get("required_status_checks") or {}
    contexts = list(checks.get("contexts") or [])
    contexts += [check.get("context") for check in checks.get("checks") or [] if isinstance(check, dict)]
    return STATUS_CONTEXT in contexts


def rules_require_status(rules, context):
    """True when an effective branch rule requires `context` as a status check. Pure: no I/O.

    `rules` is the JSON list from GET /repos/{owner}/{repo}/rules/branches/{base}. Only rules of
    type "required_status_checks" count; a missing or non-list value is not a requirement.
    """
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters") or {}
        checks = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
        if not isinstance(checks, list):
            continue
        if any(isinstance(check, dict) and check.get("context") == context for check in checks):
            return True
    return False


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


def _read_or_none(path):
    """GET path. A 404 means this source has nothing to say and returns None; other errors are raised."""
    try:
        return request("GET", path)
    except GhError as exc:
        if exc.status == 404:
            return None
        raise


def base_requires_status(owner, name, base):
    """True when classic branch protection OR the effective rules of `base` require STATUS_CONTEXT."""
    encoded = quote(base, safe="/")
    protection = _read_or_none(f"/repos/{owner}/{name}/branches/{encoded}/protection")
    rules = _read_or_none(f"/repos/{owner}/{name}/rules/branches/{encoded}")
    return protection_requires_status(protection) or rules_require_status(rules, STATUS_CONTEXT)


def enable_auto_merge(owner, name, number):
    """Enable squash auto-merge. Return GitHub's autoMergeRequest, or None when GitHub did not enable it."""
    data = graphql(PR_ID_QUERY, {"owner": owner, "name": name, "number": number})
    pull_request = (data.get("repository") or {}).get("pullRequest")
    if not pull_request:
        raise GhError(f"Pull request #{number} not found for auto-merge.")
    result = graphql(AUTO_MERGE_MUTATION, {"id": pull_request["id"]})
    return result["enablePullRequestAutoMerge"]["pullRequest"]["autoMergeRequest"]


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
    automerge_enabled = True
    if "automerge:enable" in actions:
        automerge_enabled = enable_auto_merge(owner, name, args.pr) is not None
        if not automerge_enabled:
            actions = ["automerge:not-enabled" if action == "automerge:enable" else action for action in actions]

    print("actions:")
    for action in actions:
        print(f"  {action}")
    if not automerge_enabled:
        print(
            f"error: GitHub did not enable auto-merge on #{args.pr}. The review comment and status were posted. "
            "Merge by hand or check branch protection. Do not re-run review_pr.py: it would post a second review.",
            file=sys.stderr,
        )
        return 1
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
