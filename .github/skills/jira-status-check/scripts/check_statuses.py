#!/usr/bin/env python3
"""Check that every factory state name exists as a Jira status (case-sensitive).

With no file argument, the project's statuses are read from the Jira REST API.
A file may hold a JSON list of status names or a saved project statuses response.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402


def names_in(node):
    """Collect status names from a list of strings or a saved statuses response."""
    names = set()
    if isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                names.add(item)
            else:
                names |= names_in(item)
    elif isinstance(node, dict):
        if isinstance(node.get("name"), str) and "statusCategory" in node:
            names.add(node["name"])
        for key, value in node.items():
            if key != "name":
                names |= names_in(value)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("statuses_file", nargs="?", help="optional saved statuses JSON instead of the API")
    parser.add_argument("--project", help="Jira project key (default: JIRA_PROJECT_KEY)")
    args = parser.parse_args()

    try:
        wanted = jira.state_names(jira.load_machine())
        if args.statuses_file:
            available = names_in(json.loads(Path(args.statuses_file).read_text(encoding="utf-8")))
        else:
            available = jira.project_status_names(args.project or jira.config()[1])
    except (jira.JiraError, OSError, ValueError) as err:
        print(err, file=sys.stderr)
        return 2

    missing = sorted(wanted - available)
    print(f"Checked {len(wanted)} state names against {len(available)} Jira statuses.")
    if missing:
        print(f"Missing in Jira (case-sensitive): {', '.join(missing)}")
        return 1
    print("All state names exist in Jira.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
