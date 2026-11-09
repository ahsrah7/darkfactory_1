#!/usr/bin/env python3
"""Check open tickets for duplicates, then create the ticket through the Jira REST API.

Exit codes: 0 created (or dry run), 1 refused (likely duplicate, bad input, or credential in the text), 2 Jira error.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402
from find_duplicates import open_issues  # noqa: E402

MAX_SUMMARY = 255


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", default="Story", help="issue type name, for example Story, Bug, Task, Subtask")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--description-file", type=Path, help="plain-text description from a file")
    parser.add_argument("--parent", help="parent issue key, for example an epic or a story for a subtask")
    parser.add_argument("--project", help="Jira project key (default: JIRA_PROJECT_KEY)")
    parser.add_argument("--threshold", type=float, default=0.5, help="similarity that counts as a duplicate")
    parser.add_argument("--force", action="store_true", help="file even when a likely duplicate exists")
    parser.add_argument("--dry-run", action="store_true", help="print the payload and check duplicates only")
    args = parser.parse_args()

    summary = args.summary.strip()
    if not summary or len(summary) > MAX_SUMMARY:
        print(f"Summary must be 1 to {MAX_SUMMARY} characters.", file=sys.stderr)
        return 1
    description = args.description_file.read_text(encoding="utf-8").strip() if args.description_file else ""

    try:
        base, default_project = jira.config()
        project = jira.check_project(args.project or default_project)
        if args.parent:
            jira.check_key(args.parent)
        issues = open_issues(project)
    except (jira.JiraError, OSError, ValueError) as err:
        print(err, file=sys.stderr)
        return 2

    wanted = jira.tokens(summary)
    dupes = []
    for issue in issues:
        fields = issue.get("fields") or {}
        score = jira.similarity(wanted, jira.tokens(fields.get("summary", "")))
        if score >= args.threshold:
            dupes.append((score, issue.get("key", "?"), fields.get("summary", "")))

    if dupes and not args.force:
        print("Likely duplicates. Link to one instead of filing a new ticket:")
        for score, key, text in sorted(dupes, reverse=True):
            print(f"  {key}  {score:.2f}  {text}")
        return 1

    fields = {"project": {"key": project}, "issuetype": {"name": args.type}, "summary": summary}
    if description:
        fields["description"] = description
    if args.parent:
        fields["parent"] = {"key": args.parent}

    if args.dry_run:
        print(json.dumps({"fields": fields}, indent=2))
        print("Dry run. Nothing was created.")
        return 0

    try:
        created = jira.create_issue(fields)
    except jira.CredentialInText as err:
        print(err, file=sys.stderr)
        return 1
    except jira.JiraError as err:
        print(err, file=sys.stderr)
        return 2
    print(f"Created {created['key']}: {base}/browse/{created['key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
