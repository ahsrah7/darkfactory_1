#!/usr/bin/env python3
"""Check a summary against open tickets for duplicates. Offline unless --search-file is omitted.

With --search-file, read a saved search response. Without it, query the project through the REST API.
Exit codes: 0 no likely duplicate, 1 likely duplicate, 2 Jira error.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402


def open_issues(project):
    jql = f'project = "{project}" AND statusCategory != Done ORDER BY updated DESC'
    return jira.search(jql, ["summary"], limit=500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, help="summary of the ticket about to be filed")
    parser.add_argument("--search-file", type=Path, help="saved search response instead of the API")
    parser.add_argument("--project", help="Jira project key (default: JIRA_PROJECT_KEY)")
    parser.add_argument("--threshold", type=float, default=0.5, help="similarity that counts as a duplicate")
    args = parser.parse_args()

    try:
        if args.search_file:
            issues = jira.find_issues(json.loads(args.search_file.read_text(encoding="utf-8"))) or []
        else:
            issues = open_issues(jira.check_project(args.project or jira.config()[1]))
    except (jira.JiraError, OSError, ValueError) as err:
        print(err, file=sys.stderr)
        return 2

    wanted = jira.tokens(args.summary)
    matches = []
    for issue in issues:
        fields = issue.get("fields") or {}
        score = jira.similarity(wanted, jira.tokens(fields.get("summary", "")))
        if score >= args.threshold:
            matches.append((score, issue.get("key", "?"), fields.get("summary", "")))

    if not matches:
        print("No likely duplicates. Safe to file.")
        return 0
    print("Likely duplicates. Link to one instead of filing a new ticket:")
    for score, key, summary in sorted(matches, reverse=True):
        print(f"  {key}  {score:.2f}  {summary}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
