"""Open a pull request for a factory branch, or update the open one.

Usage: open_pr.py --head NAME --title TITLE --body-file FILE [--base main] [--dry-run]

Exit codes: 0 done; 1 GitHub error; 2 refused input.
"""

import argparse
import sys
from urllib.parse import urlencode

from gh_client import GhError, configure_output, repo, request
from publish_branch import validate_branch

MAX_TITLE_LENGTH = 256


def normalize_body(text):
    """Strip trailing whitespace. GitHub returns HTTP 500 for bodies with a trailing newline."""
    body = text.rstrip()
    if not body:
        raise ValueError("PR body is empty")
    return body


def normalize_title(title):
    value = title.strip()
    if not value:
        raise ValueError("PR title is empty")
    if len(value) > MAX_TITLE_LENGTH:
        raise ValueError(f"PR title is {len(value)} characters; the limit is {MAX_TITLE_LENGTH}")
    return value


def find_open_pr(owner, name, head):
    query = urlencode({"head": f"{owner}:{head}", "state": "open", "per_page": 100})
    pulls = request("GET", f"/repos/{owner}/{name}/pulls?{query}") or []
    return pulls[0] if pulls else None


def _execute(args, title, body):
    owner, name = repo()
    existing = find_open_pr(owner, name, args.head)
    body_bytes = len(body.encode("utf-8"))

    if args.dry_run:
        if existing:
            print(f"dry run: would update #{existing['number']} {existing['html_url']}")
        else:
            print(f"dry run: would create a PR head={args.head} base={args.base}")
        print(f"dry run: title {len(title)} chars, body {body_bytes} bytes; no writes made")
        return 0

    if existing:
        pr = request(
            "PATCH",
            f"/repos/{owner}/{name}/pulls/{existing['number']}",
            {"title": title, "body": body},
        )
        print(f"updated #{pr['number']} {pr['html_url']}")
        return 0

    pr = request(
        "POST",
        f"/repos/{owner}/{name}/pulls",
        {"title": title, "head": args.head, "base": args.base, "body": body},
    )
    print(f"created #{pr['number']} {pr['html_url']}")
    return 0


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Open or update the PR for a factory branch.")
    parser.add_argument("--head", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    problems = validate_branch(args.head)
    if args.head == args.base:
        problems.append("head and base must differ")
    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        return 2

    try:
        title = normalize_title(args.title)
        with open(args.body_file, encoding="utf-8-sig") as handle:
            body = normalize_body(handle.read())
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    try:
        return _execute(args, title, body)
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
