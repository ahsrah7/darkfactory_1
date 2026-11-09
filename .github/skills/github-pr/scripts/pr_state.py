"""Print the state of a pull request. Read-only.

Usage: pr_state.py --pr N

Exit codes: 0 printed; 1 GitHub error.
"""

import argparse
import sys
from urllib.parse import quote

from gh_client import (
    STATUS_CONTEXT,
    GhError,
    configure_output,
    count_request_changes,
    repo,
    request,
    request_all,
)


def summarize_checks(runs):
    """Return 'name=value' for each check name, using the newest run per name."""
    latest = {}
    for run in runs:
        name = run.get("name") or "?"
        run_id = run.get("id") or 0
        value = run.get("conclusion") or run.get("status") or "unknown"
        if name not in latest or run_id >= latest[name][0]:
            latest[name] = (run_id, value)
    return [f"{name}={value}" for name, (_, value) in sorted(latest.items())]


def newest_status(statuses, context):
    """Return the state of the newest commit status with this context, or 'none'."""
    matches = [status for status in statuses if status.get("context") == context]
    if not matches:
        return "none"
    newest = max(matches, key=lambda status: (status.get("created_at") or "", status.get("id") or 0))
    return newest.get("state") or "none"


def _execute(number):
    owner, name = repo()
    pr = request("GET", f"/repos/{owner}/{name}/pulls/{number}")
    head_sha = pr["head"]["sha"]
    base = pr["base"]["ref"]
    auto_merge = "on" if pr.get("auto_merge") else "off"

    compare = request("GET", f"/repos/{owner}/{name}/compare/{quote(base, safe='/')}...{head_sha}")
    runs = request_all(f"/repos/{owner}/{name}/commits/{head_sha}/check-runs", key="check_runs")
    statuses = request_all(f"/repos/{owner}/{name}/commits/{head_sha}/statuses")
    comments = request_all(f"/repos/{owner}/{name}/issues/{number}/comments")

    checks = summarize_checks(runs)
    lines = [
        f"#{pr['number']} state={pr['state']} head={pr['head']['ref']} base={base} head_sha={head_sha[:7]}",
        f"mergeable_state={pr.get('mergeable_state') or 'unknown'} auto_merge={auto_merge}",
        f"behind_base={compare.get('behind_by', 'unknown')}",
        "checks: " + (" ".join(checks) if checks else "none"),
        f"status {STATUS_CONTEXT}={newest_status(statuses, STATUS_CONTEXT)}",
        f"rework_rounds={count_request_changes(comments)}",
    ]
    print("\n".join(lines))
    return 0


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Print the state of a pull request. Read-only.")
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        return _execute(args.pr)
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
