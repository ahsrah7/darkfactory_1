#!/usr/bin/env python3
"""Read a project's tickets from Jira and group them by status name."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402
from bounded_jql import build, check  # noqa: E402

FIELDS = ["summary", "status", "issuetype"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Jira project key (default: JIRA_PROJECT_KEY)")
    parser.add_argument("--days", type=int, default=90, help="look-back window in days (default 90)")
    parser.add_argument("--jql", help="custom JQL; it must still be bounded")
    args = parser.parse_args()

    try:
        project = jira.check_project(args.project or jira.config()[1])
        jql = check(args.jql) if args.jql else build(project, args.days)
        issues = jira.search(jql, FIELDS)
        known = jira.state_names(jira.load_machine())
    except jira.JiraError as err:
        print(err, file=sys.stderr)
        return 2
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1

    groups = {}
    for issue in issues:
        status = (issue.get("fields") or {}).get("status", {}).get("name") or "<no status>"
        groups.setdefault(status, []).append(issue.get("key", "?"))

    unknown = []
    for status in sorted(groups):
        flag = ""
        if status not in known:
            flag = "  NOT IN STATE MACHINE"
            unknown.append(status)
        print(f"{len(groups[status]):>3}  {status}{flag}: {', '.join(sorted(groups[status]))}")
    print(f"total: {len(issues)}")

    if unknown:
        print(f"Statuses not in state-machine.json (case-sensitive): {', '.join(unknown)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
