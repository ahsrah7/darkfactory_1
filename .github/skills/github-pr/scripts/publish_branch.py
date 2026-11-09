"""Commit and push a factory branch, limited to the given paths.

Usage: publish_branch.py --branch NAME --scope PATH [--scope PATH ...] --message MSG [--dry-run]

Exit codes: 0 published, dry run done, or nothing to publish; 1 git failed;
2 refused input; 3 staged paths outside the scopes (nothing committed).
Never pushes with --force or --force-with-lease.
"""

import argparse
import subprocess
import sys

from gh_client import configure_output

PROTECTED_BRANCHES = ("main", "master")
TRAILER = "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
EXIT_OK = 0
EXIT_GIT = 1
EXIT_REFUSED = 2
EXIT_OUTSIDE_SCOPE = 3


def _normalize(path):
    return path.replace("\\", "/")


def _clean_scope(scope):
    path = _normalize(scope).strip()
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def _is_absolute(scope):
    path = _normalize(scope)
    return path.startswith("/") or (len(path) > 1 and path[1] == ":")


def validate_branch(name):
    """Return a list of problems with a branch name. An empty list means valid."""
    if not name or name.startswith("-"):
        return ["branch name is empty or starts with '-'"]
    if name in PROTECTED_BRANCHES:
        return [f"refusing to publish to protected branch '{name}'"]
    if name.startswith("origin/"):
        return ["branch name must be local, not 'origin/...'"]
    return []


def validate_scopes(scopes):
    """Return a list of problems with the --scope values. An empty list means valid."""
    if not scopes:
        return ["at least one --scope is required"]
    problems = []
    for scope in scopes:
        if not scope.strip():
            problems.append("scope is empty")
        elif _is_absolute(scope):
            problems.append(f"scope must be relative: {scope}")
        elif ".." in scope:
            problems.append(f"scope must not contain '..': {scope}")
        elif _clean_scope(scope) in ("", "."):
            problems.append(f"scope must name a path, not the repository root: {scope}")
    return problems


def paths_within_scopes(paths, scopes):
    """Return the paths that sit outside every scope. A scope is a directory prefix or an exact file."""
    cleaned = [_clean_scope(scope) for scope in scopes]
    outside = []
    for path in paths:
        normalized = _normalize(path)
        if not any(normalized == scope or normalized.startswith(scope + "/") for scope in cleaned):
            outside.append(path)
    return outside


def _git(*args, stdin=None):
    return subprocess.run(
        ["git", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _report_failure(label, result):
    detail = (result.stderr or result.stdout or "").strip()
    print(f"error: {label} failed: {detail}", file=sys.stderr)
    return EXIT_GIT


def _unstage():
    result = _git("restore", "--staged", ".")
    if result.returncode != 0:
        print(f"warning: could not unstage: {(result.stderr or '').strip()}", file=sys.stderr)


def _ensure_branch(name):
    """Switch to the branch, creating it locally if needed. Returns an exit code on failure, else None."""
    current = _git("rev-parse", "--abbrev-ref", "HEAD")
    if current.returncode != 0:
        return _report_failure("reading the current branch", current)
    if current.stdout.strip() == name:
        return None
    exists = _git("show-ref", "--verify", "--quiet", f"refs/heads/{name}")
    if exists.returncode == 0:
        switched = _git("switch", name)
    else:
        switched = _git("switch", "-c", name)
    if switched.returncode != 0:
        return _report_failure(f"switching to {name}", switched)
    return None


def _summarize_push(output):
    for line in output.splitlines():
        if "->" in line:
            return line.strip()
    return "ok"


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(
        description="Commit and push a factory branch, limited to the given paths."
    )
    parser.add_argument("--branch", required=True)
    parser.add_argument("--scope", action="append", required=True, metavar="PATH")
    parser.add_argument("--message", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    problems = validate_branch(args.branch) + validate_scopes(args.scope)
    if not args.message.strip():
        problems.append("--message must not be empty")
    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        return EXIT_REFUSED

    failed = _ensure_branch(args.branch)
    if failed is not None:
        return failed

    scopes = [_clean_scope(scope) for scope in args.scope]
    added = _git("add", "--", *scopes)
    if added.returncode != 0:
        return _report_failure("staging the scopes", added)

    listed = _git("diff", "--cached", "--name-only", "-z")
    if listed.returncode != 0:
        return _report_failure("listing staged paths", listed)
    paths = [path for path in listed.stdout.split("\0") if path]
    if not paths:
        print("nothing to publish")
        return EXIT_OK

    outside = paths_within_scopes(paths, scopes)
    if outside:
        _unstage()
        print("refused: staged paths outside the scopes (nothing committed):", file=sys.stderr)
        for path in outside:
            print(f"  {path}", file=sys.stderr)
        return EXIT_OUTSIDE_SCOPE

    if args.dry_run:
        print(f"dry run: would commit {len(paths)} path(s) to {args.branch}:")
        for path in paths:
            print(f"  {path}")
        print(f"message: {args.message.strip()}")
        print(f"trailer: {TRAILER}")
        _unstage()
        return EXIT_OK

    message = f"{args.message.strip()}\n\n{TRAILER}\n"
    committed = _git("commit", "-F", "-", stdin=message)
    if committed.returncode != 0:
        return _report_failure("commit", committed)
    short_sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"committed {short_sha} on {args.branch}")

    pushed = _git("push", "-u", "origin", args.branch)
    output = (pushed.stderr or pushed.stdout or "").strip()
    if pushed.returncode != 0:
        print(f"error: push failed: {output}", file=sys.stderr)
        return EXIT_GIT
    print(f"pushed: {_summarize_push(output)}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
