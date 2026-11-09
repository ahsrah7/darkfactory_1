"""Print the newest request-changes review comment and the inline review comments. Read-only.

Usage: pr_feedback.py --pr N

Exit codes: 0 printed; 1 GitHub error.
"""

import argparse
import sys

from gh_client import GhError, configure_output, is_request_changes, repo, request_all


def newest_request_changes(comments):
    marked = [comment for comment in comments if is_request_changes(comment)]
    if not marked:
        return None
    return max(marked, key=lambda comment: comment.get("created_at") or "")


def format_inline(comment):
    line = comment.get("line") or comment.get("original_line") or "?"
    return f"{comment.get('path') or '?'}:{line} - {comment.get('body') or ''}"


def _execute(number):
    owner, name = repo()
    comments = request_all(f"/repos/{owner}/{name}/issues/{number}/comments")
    newest = newest_request_changes(comments)
    if newest is None:
        print("no request-changes comment found")
        return 0

    print(newest.get("body") or "")
    print()
    inline = request_all(f"/repos/{owner}/{name}/pulls/{number}/comments")
    if not inline:
        print("inline review comments: none")
    for comment in inline:
        print(format_inline(comment))
    return 0


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Print review feedback for a pull request. Read-only.")
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        return _execute(args.pr)
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
