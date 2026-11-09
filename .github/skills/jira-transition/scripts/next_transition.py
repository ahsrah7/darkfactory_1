#!/usr/bin/env python3
"""Show the next status for a ticket from state-machine.json, without calling Jira.

Exit codes: 0 move (target printed), 2 no transition, 3 refused.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", help="current status name, case-sensitive")
    parser.add_argument("outcome", help="outcome key, for example onSuccess, onApproved, onRejected")
    args = parser.parse_args()

    target, reason, refused = jira.next_status(jira.load_machine(), args.current, args.outcome)
    if target is None:
        print(reason, file=sys.stderr)
        return 3 if refused else 2
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
