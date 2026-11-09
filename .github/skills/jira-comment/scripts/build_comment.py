#!/usr/bin/env python3
"""Build a factory Jira comment, and optionally post or edit it.

Without --issue, the body is printed. With --issue, it is posted to that ticket.
With --issue and --comment-id, that comment is replaced instead.

Exit codes: 0 ok, 1 bad arguments or credential in the text, 2 Jira error.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jira-api" / "scripts"))
import jira_api as jira  # noqa: E402


def build(args):
    lines = [f"{args.agent}" + (f" ({args.mode})" if args.mode else "") + " outcome."]
    if args.from_status == args.to_status:
        lines.append(f"Status unchanged: {args.to_status}. {args.reason or ''}".rstrip())
    else:
        lines.append(f"Status: {args.from_status} to {args.to_status}. {args.reason or ''}".rstrip())
    if args.evidence:
        lines.append("")
        lines.append("Evidence:")
        for item in args.evidence:
            label, _, link = item.partition("=")
            lines.append(f"- {label.strip()}: {link.strip()}")
    if args.next:
        lines.append("")
        lines.append(f"Next: {args.next}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, help="agent name, for example software-developer")
    parser.add_argument("--mode", help="agent mode, for example refine or write")
    parser.add_argument("--from-status", required=True)
    parser.add_argument("--to-status", required=True)
    parser.add_argument("--reason", help="one factual sentence")
    parser.add_argument("--evidence", action="append", metavar="LABEL=URL", help="repeatable evidence link")
    parser.add_argument("--next", help="what happens next or what a human must do")
    parser.add_argument("--issue", help="issue key to post the comment on, for example SCRUM-7")
    parser.add_argument("--comment-id", help="existing comment id to replace (needs --issue)")
    args = parser.parse_args()

    if args.comment_id and not args.issue:
        print("--comment-id needs --issue.", file=sys.stderr)
        return 1

    comment = build(args)

    if not args.issue:
        print(comment, end="")
        return 0

    try:
        if args.comment_id:
            saved = jira.edit_comment(args.issue, args.comment_id, comment)
        else:
            saved = jira.add_comment(args.issue, comment)
    except jira.CredentialInText as err:
        print(err, file=sys.stderr)
        return 1
    except jira.JiraError as err:
        print(err, file=sys.stderr)
        return 2
    print(f"{args.issue}: comment {saved['id']} saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
