"""Shared GitHub REST and GraphQL client for the factory PR scripts.

Standard library only. The token comes from GITHUB_TOKEN, then GH_TOKEN, then
the user-scope GITHUB_TOKEN in HKCU\\Environment (Windows). It is never printed,
logged or written to a file, and it is redacted from error text.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

try:
    import winreg
except ImportError:
    winreg = None

API = "https://api.github.com"
USER_AGENT = "factory-pr-automation"
STATUS_CONTEXT = "factory/review"
REQUEST_CHANGES_MARKER = "<!-- factory-review:request-changes -->"
PAGE_SIZE = 100
ERROR_LIMIT = 300
TIMEOUT_SECONDS = 60
GITHUB_PREFIXES = (
    "https://github.com/",
    "http://github.com/",
    "ssh://git@github.com/",
    "git@github.com:",
)


class GhError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def configure_output():
    """Let PR text with non-ASCII characters print on consoles that are not UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _registry_token():
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "GITHUB_TOKEN")
    except OSError:
        return ""
    return str(value or "").strip()


def token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    value = _registry_token()
    if value:
        return value
    raise GhError("No GitHub token found in GITHUB_TOKEN or GH_TOKEN.")


def _split_owner_repo(value):
    owner, sep, name = value.partition("/")
    if not sep or not owner or not name or "/" in name:
        return None
    return owner, name


def parse_remote(url):
    """Return (owner, name) from a github.com remote URL. The URL is never echoed."""
    value = url.strip()
    for prefix in GITHUB_PREFIXES:
        if value.startswith(prefix):
            path = value[len(prefix):].rstrip("/")
            break
    else:
        raise GhError("origin is not a github.com remote. Set GITHUB_REPOSITORY=OWNER/REPO.")
    if path.endswith(".git"):
        path = path[:-4]
    pair = _split_owner_repo(path)
    if pair is None:
        raise GhError("Cannot read OWNER/REPO from the origin remote. Set GITHUB_REPOSITORY=OWNER/REPO.")
    return pair


def repo():
    value = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if value:
        pair = _split_owner_repo(value)
        if pair is None:
            raise GhError("GITHUB_REPOSITORY must be OWNER/REPO.")
        return pair
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        raise GhError("git is not available to read the origin remote.") from None
    if result.returncode != 0:
        raise GhError("Cannot read the origin remote. Set GITHUB_REPOSITORY=OWNER/REPO.")
    return parse_remote(result.stdout)


def _redact(text, secret):
    return text.replace(secret, "[redacted]") if secret else text


def _error_text(raw, secret):
    text = raw.decode("utf-8", "replace") if raw else ""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        text = parsed["message"]
    return _redact(text.strip(), secret)[:ERROR_LIMIT]


def request(method, path, body=None):
    """Call the GitHub REST API. Returns parsed JSON, or None for an empty response."""
    secret = token()
    headers = {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read()
        except OSError:
            raw_error = b""
        message = _error_text(raw_error, secret)
        raise GhError(
            f"{method} {path} failed: HTTP {exc.code} {message}", status=exc.code
        ) from None
    except urllib.error.URLError as exc:
        reason = _redact(str(exc.reason), secret)
        raise GhError(f"{method} {path} failed: network error ({reason})") from None
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def request_all(path, key=None):
    """Return every item across pages. Pass key when the list sits under an object field."""
    items = []
    page = 1
    joiner = "&" if "?" in path else "?"
    while True:
        data = request("GET", f"{path}{joiner}per_page={PAGE_SIZE}&page={page}")
        if key and isinstance(data, dict):
            batch = data.get(key) or []
        else:
            batch = data or []
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
        page += 1


def graphql(query, variables=None):
    data = request("POST", "/graphql", {"query": query, "variables": variables or {}})
    errors = data.get("errors") if isinstance(data, dict) else None
    if errors:
        messages = "; ".join(
            str(error.get("message", "unknown error")) for error in errors if isinstance(error, dict)
        )
        raise GhError(f"POST /graphql failed: {_redact(messages, token())[:ERROR_LIMIT]}")
    return (data or {}).get("data") or {}


def is_request_changes(comment):
    """True only when the marker is the first line of the comment body."""
    first_line = ((comment.get("body") or "").splitlines() or [""])[0]
    return first_line.strip() == REQUEST_CHANGES_MARKER


def count_request_changes(comments):
    return sum(1 for comment in comments if is_request_changes(comment))
