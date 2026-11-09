#!/usr/bin/env python3
"""Build a bounded JQL query for a Jira project, or check one that already exists."""

import argparse
import re
import sys

PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
# Jira rejects JQL with no search restriction. Accept a project, issue key or parent clause, or a date bound.
RESTRICTION = re.compile(
    r"\b(project|issuekey|key|parent)\s*(=|in\b|~)"
    r"|\b(created|updated|resolved|duedate)\s*(>=|>|<=|<|=)",
    re.IGNORECASE,
)


def build(project, days):
    if not PROJECT_KEY.match(project):
        raise ValueError(f"Invalid project key: {project!r}. Use upper-case letters, digits and underscores.")
    if days < 1:
        raise ValueError("--days must be at least 1.")
    return f'project = "{project}" AND updated >= -{days}d ORDER BY updated DESC'


def check(jql):
    if not RESTRICTION.search(jql):
        raise ValueError("Unbounded JQL. Add a project, key or date restriction.")
    return jql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Jira project key, for example SCRUM")
    parser.add_argument("--days", type=int, default=90, help="look-back window in days (default 90)")
    parser.add_argument("--check", metavar="JQL", help="check an existing JQL string instead of building one")
    args = parser.parse_args()

    try:
        if args.check is not None:
            print(check(args.check))
        elif args.project:
            print(build(args.project, args.days))
        else:
            parser.error("give --project or --check")
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
