#!/usr/bin/env python3
"""Move a Jira ticket to the next status from state-machine.json through the REST API.

Exit codes: 0 moved (or dry run), 1 Jira or config error, 2 no single transition,
3 refused by the state machine, 4 the status after the move did not match the target.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key", help="issue key, for example SCRUM-7")
    parser.add_argument("outcome", help="outcome key, for example onSuccess, onApproved, onRejected")
    parser.add_argument("--dry-run", action="store_true", help="show the move without making it")
    args = parser.parse_args()

    try:
        key = jira.check_key(args.key)
        current = jira.get_issue(key, ["status"])["fields"]["status"]["name"]
        target, reason, refused = jira.next_status(jira.load_machine(), current, args.outcome)
        if target is None:
            print(reason, file=sys.stderr)
            return 3 if refused else 2

        matches = [t for t in jira.list_transitions(key) if t.get("to", {}).get("name") == target]
        if len(matches) > 1:
            specific = [t for t in matches if current in t.get("name", "")]
            if len(specific) == 1:
                matches = specific
        if len(matches) != 1:
            print(f"{key}: {len(matches)} Jira transitions from {current!r} to {target!r}; need exactly one. Set Blocked.",
                  file=sys.stderr)
            return 2

        if args.dry_run:
            print(f"{key}: would move {current} -> {target} (transition {matches[0]['id']})")
            return 0

        jira.do_transition(key, matches[0]["id"])
        now = jira.get_issue(key, ["status"])["fields"]["status"]["name"]
    except jira.JiraError as err:
        print(err, file=sys.stderr)
        return 1

    if now != target:
        print(f"{key}: status is {now!r} after the move, expected {target!r}. Set Blocked.", file=sys.stderr)
        return 4
    print(f"{key}: {current} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
