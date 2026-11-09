"""Commit and push a factory branch, limited to the given paths.

Usage: publish_branch.py --branch NAME --scope PATH [--scope PATH ...] --message MSG [--dry-run]

Exit codes: 0 published, dry run done, or nothing to publish; 1 git failed or no
remote base found; 2 refused input (including a missing --scope); 3 staged paths or
unpushed commits outside the scopes (nothing committed, nothing pushed).

Unpushed commits are every commit in base..BRANCH, where base is origin/NAME when
that ref exists, else origin/main. If neither exists the unpushed state is unknown,
so the script exits 1 with "no remote base found; fetch origin before publishing"
and changes nothing. It never counts commits as published on a guess, and it never
reports "nothing to publish" in that case.

Every unpushed commit is checked against the scopes before anything is pushed.
Each commit's changed paths are read one commit at a time with --no-renames, merges
included. A commit that adds an out-of-scope file and a later commit that removes it
are still refused. A push-when-ahead always has a scope, because --scope is required.

With nothing staged, it still pushes local commits the remote does not have yet,
after the scope check above. Remote URLs are printed as "origin" in all output.
--dry-run changes no git state: it does not switch or create branches, does not
stage files and does not write the index. It applies the same checks and lists what
a real run would commit and how many commits it would push.
Staged paths are read with --no-renames, so a rename out of scope shows both paths.
Never pushes with --force or --force-with-lease.
"""

import argparse
import re
import subprocess
import sys

from gh_client import configure_output

PROTECTED_BRANCHES = ("main", "master")
TRAILER = "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
NO_BASE_MESSAGE = "no remote base found; fetch origin before publishing"
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
        elif _has_parent_segment(scope):
            problems.append(f"scope must not contain a '..' path segment: {scope}")
        elif _clean_scope(scope) in ("", "."):
            problems.append(f"scope must name a path, not the repository root: {scope}")
    return problems


def _has_parent_segment(scope):
    """True only when a path segment is exactly '..', so 'a..b' is a normal name."""
    return ".." in _normalize(scope).split("/")


def _within(path, cleaned_scopes):
    normalized = _normalize(path)
    return any(normalized == scope or normalized.startswith(scope + "/") for scope in cleaned_scopes)


def paths_within_scopes(paths, scopes):
    """Return the paths that sit outside every scope. A scope is a directory prefix or an exact file."""
    cleaned = [_clean_scope(scope) for scope in scopes]
    return [path for path in paths if not _within(path, cleaned)]


def parse_status(output):
    """Return (staged, path) pairs from `git status --porcelain -z --no-renames` output."""
    entries = []
    for entry in output.split("\0"):
        if len(entry) < 4:
            continue
        index_state = entry[0]
        entries.append((index_state not in " ?!", entry[3:]))
    return entries


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


def _origin_urls():
    """Every URL configured for origin, fetch and push. Empty when origin is not set."""
    found = _git("config", "--get-regexp", r"^remote\.origin\.(url|pushurl)$")
    if found.returncode != 0:
        return []
    urls = []
    for line in found.stdout.splitlines():
        value = line.partition(" ")[2].strip()
        if value:
            urls.append(value)
    return urls


def _redact(text, urls):
    """Print origin's URL as 'origin', and drop user:password@ from any other URL in the text."""
    for url in sorted(set(urls), key=len, reverse=True):
        text = text.replace(url, "origin")
    return re.sub(r"([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1", text, flags=re.IGNORECASE)


def _report_failure(label, result):
    detail = _redact((result.stderr or result.stdout or "").strip(), _origin_urls())
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


STAGED_HEADING = "staged paths outside the scopes (nothing committed):"
UNPUSHED_HEADING = "unpushed commits change paths outside the scopes (nothing pushed):"


def _refuse_outside_scope(outside, heading):
    print(f"refused: {heading}", file=sys.stderr)
    for path in outside:
        print(f"  {path}", file=sys.stderr)
    return EXIT_OUTSIDE_SCOPE


def _dry_run(args, scopes):
    """Report what a real run would commit and push. Reads git state only: no branch, staging or index writes."""
    status = _git(
        "--no-optional-locks", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all"
    )
    if status.returncode != 0:
        return _report_failure("reading the working tree status", status)
    entries = parse_status(status.stdout)
    staged_outside = paths_within_scopes([path for staged, path in entries if staged], scopes)
    if staged_outside:
        return _refuse_outside_scope(staged_outside, STAGED_HEADING)
    code, _, pending = _check_unpushed(_publish_tip(args.branch), args.branch, scopes)
    if code is not None:
        return code
    would_commit = [path for _, path in entries if not paths_within_scopes([path], scopes)]
    if not would_commit and pending == 0:
        print("nothing to publish")
        return EXIT_OK
    if would_commit:
        print(f"dry run: would commit {len(would_commit)} path(s) to {args.branch}:")
        for path in would_commit:
            print(f"  {path}")
        print(f"message: {args.message.strip()}")
        print(f"trailer: {TRAILER}")
    total = pending + (1 if would_commit else 0)
    noun = "commit" if total == 1 else "commits"
    print(f"dry run: would push {total} {noun} to origin/{args.branch}")
    print("dry run: no branch, index or file was changed")
    return EXIT_OK


def _summarize_push(output):
    for line in output.splitlines():
        if "->" in line:
            return line.strip()
    return "ok"


def _ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", ref).returncode == 0


def _publish_tip(name):
    """The commit a real run would push: the branch itself if it exists, else HEAD (which the real run branches from)."""
    return name if _ref_exists(f"refs/heads/{name}") else "HEAD"


def _remote_base(name):
    """origin/NAME when that ref exists, else origin/main, else None. There is no other fallback."""
    if _ref_exists(f"refs/remotes/origin/{name}"):
        return f"origin/{name}"
    if _ref_exists("refs/remotes/origin/main"):
        return "origin/main"
    return None


def _unpushed_paths(base, tip):
    """Sorted paths that any commit in base..tip changes. Returns (paths, failed_result).

    git log lists each commit's own changes, one commit at a time, with renames off. -m covers
    merges against every parent. A file a commit adds and a later commit removes still shows up.
    """
    listed = _git("log", "-m", "--no-renames", "--name-only", "-z", "--format=", f"{base}..{tip}")
    if listed.returncode != 0:
        return None, listed
    return sorted({path for path in listed.stdout.split("\0") if path}), None


def _check_unpushed(tip, name, scopes):
    """Check every commit a push of tip would send beyond the remote base against the scopes.

    Returns (code, base, count). code is None when all of them are in scope. Otherwise code is the
    exit code to return and the reason has already been printed. Exits 1 with NO_BASE_MESSAGE when
    no remote base exists, because the unpushed state is then unknown and nothing is counted as published.
    count is the number of unpushed commits.
    """
    base = _remote_base(name)
    if base is None:
        print(f"error: {NO_BASE_MESSAGE}", file=sys.stderr)
        return EXIT_GIT, None, None
    counted = _git("rev-list", "--count", f"{base}..{tip}")
    if counted.returncode != 0:
        return _report_failure("counting unpublished commits", counted), None, None
    paths, failed = _unpushed_paths(base, tip)
    if failed is not None:
        return _report_failure("listing unpublished paths", failed), None, None
    outside = paths_within_scopes(paths, scopes)
    if outside:
        return _refuse_outside_scope(outside, UNPUSHED_HEADING), None, None
    return None, base, int(counted.stdout.strip())


def _push(name):
    """Push with -u. Never forced. Returns (exit code, summary of the pushed range). Remote URLs are redacted."""
    pushed = _git("push", "-u", "origin", name)
    output = _redact((pushed.stderr or pushed.stdout or "").strip(), _origin_urls())
    if pushed.returncode != 0:
        print(f"error: push failed: {output}", file=sys.stderr)
        return EXIT_GIT, ""
    return EXIT_OK, _summarize_push(output)


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

    scopes = [_clean_scope(scope) for scope in args.scope]
    if args.dry_run:
        return _dry_run(args, scopes)

    failed = _ensure_branch(args.branch)
    if failed is not None:
        return failed

    # Checked before staging, so a refusal here leaves the index and HEAD untouched.
    code, base, pending = _check_unpushed(args.branch, args.branch, scopes)
    if code is not None:
        return code

    added = _git("add", "--", *scopes)
    if added.returncode != 0:
        return _report_failure("staging the scopes", added)

    listed = _git("diff", "--cached", "--no-renames", "--name-only", "-z")
    if listed.returncode != 0:
        return _report_failure("listing staged paths", listed)
    paths = [path for path in listed.stdout.split("\0") if path]
    if not paths:
        if pending == 0:
            print("nothing to publish")
            return EXIT_OK
        code, summary = _push(args.branch)
        if code != EXIT_OK:
            return code
        print(f"pushed {pending} unpublished commit(s) from {base}: {summary}")
        return EXIT_OK

    outside = paths_within_scopes(paths, scopes)
    if outside:
        _unstage()
        return _refuse_outside_scope(outside, STAGED_HEADING)

    message = f"{args.message.strip()}\n\n{TRAILER}\n"
    committed = _git("commit", "-F", "-", stdin=message)
    if committed.returncode != 0:
        return _report_failure("commit", committed)
    short_sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"committed {short_sha} on {args.branch}")

    code, summary = _push(args.branch)
    if code != EXIT_OK:
        return code
    print(f"pushed: {summary}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
