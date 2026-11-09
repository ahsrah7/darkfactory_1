"""Shared Jira REST client and factory helpers for the skill scripts.

Credentials come only from runner environment variables: JIRA_BASE_URL, JIRA_EMAIL,
JIRA_API_TOKEN and JIRA_PROJECT_KEY. They are never printed, logged or written to disk.
"""

import base64
import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MACHINE_PATH = Path(__file__).resolve().parents[3] / "factory" / "state-machine.json"
REQUIRED_ENV = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY")
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
STOP_WORDS = {"a", "an", "and", "the", "of", "to", "for", "in", "on", "with", "fail", "failing"}
SECRET_PATTERNS = {
    "Atlassian API token": re.compile(r"ATATT[0-9A-Za-z_\-]{10,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "credential assignment": re.compile(r"(?i)(api[_-]?token|password|secret|token)\s*[:=]\s*\S{6,}"),
}


class JiraError(Exception):
    """A Jira call or configuration problem. The message never contains a credential."""


class CredentialInText(JiraError):
    """Text headed for Jira contains a credential. Nothing was posted."""


def config():
    """Return (base_url, default_project_key) from the environment, or raise JiraError."""
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise JiraError(f"Missing env: {', '.join(missing)}")
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS:
        raise JiraError("JIRA_BASE_URL must use https.")
    return base, os.environ["JIRA_PROJECT_KEY"]


def request(method, path, body=None, query=None):
    """Call the Jira REST API and return parsed JSON, or None for an empty response."""
    base, _ = config()
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    token = f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}".encode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Basic {base64.b64encode(token).decode()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:500]
        raise JiraError(f"Jira {method} {path} failed: {err.code} {detail}") from None
    except urllib.error.URLError as err:
        raise JiraError(f"Jira {method} {path} unreachable: {err.reason}") from None
    except (http.client.HTTPException, OSError) as err:
        raise JiraError(f"Jira {method} {path} failed: {type(err).__name__}") from None
    return json.loads(raw) if raw else None


def check_key(key):
    if not ISSUE_KEY.match(key):
        raise JiraError(f"Invalid issue key: {key!r}. Expected a form like SCRUM-7.")
    return key


def check_project(project):
    if not PROJECT_KEY.match(project):
        raise JiraError(f"Invalid project key: {project!r}. Use upper-case letters, digits and underscores.")
    return project


def search(jql, fields, limit=None):
    """Run a bounded JQL search and follow nextPageToken until the last page or limit."""
    issues = []
    token = None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        page = request("POST", "/rest/api/3/search/jql", body=body)
        issues.extend(page.get("issues", []))
        token = page.get("nextPageToken")
        if page.get("isLast", True) or not token or (limit and len(issues) >= limit):
            return issues[:limit] if limit else issues


def get_issue(key, fields):
    return request("GET", f"/rest/api/3/issue/{check_key(key)}", query={"fields": ",".join(fields)})


def project_status_names(project):
    """Every status name used by any issue type in the project."""
    data = request("GET", f"/rest/api/3/project/{check_project(project)}/statuses")
    return {status["name"] for issue_type in data for status in issue_type.get("statuses", [])}


def list_transitions(key):
    return request("GET", f"/rest/api/3/issue/{check_key(key)}/transitions").get("transitions", [])


def do_transition(key, transition_id):
    request("POST", f"/rest/api/3/issue/{check_key(key)}/transitions", body={"transition": {"id": transition_id}})


def check_no_credentials(values):
    """Raise CredentialInText if any string in values looks like a credential. Reports the pattern name only."""
    stack = list(values)
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(item):
                    raise CredentialInText(f"Refused: text for Jira looks like it contains a credential ({name}). Nothing was posted. Remove it and tell the human to revoke it.")


def add_comment(key, text):
    check_no_credentials([text])
    return request("POST", f"/rest/api/2/issue/{check_key(key)}/comment", body={"body": text})


def list_comments(key):
    return request("GET", f"/rest/api/2/issue/{check_key(key)}/comment").get("comments", [])


def edit_comment(key, comment_id, text):
    check_no_credentials([text])
    return request("PUT", f"/rest/api/2/issue/{check_key(key)}/comment/{comment_id}", body={"body": text})


def create_issue(fields):
    check_no_credentials([fields])
    return request("POST", "/rest/api/2/issue", body={"fields": fields})


def load_machine(path=MACHINE_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def state_names(machine):
    """Every state name in the state machine, excluding 'previous status'."""
    names = set()
    for transition in machine["transitions"]:
        for key, value in transition.items():
            if key == "from" or (key.startswith("on") and isinstance(value, str)):
                names.add(value)
    names.discard("previous status")
    return names


def next_status(machine, current, outcome):
    """Return (target, reason, refused). target is None when no move is allowed."""
    if current == "Blocked":
        return None, "Blocked tickets move only by a human.", True
    for transition in machine["transitions"]:
        if transition.get("from") != current or outcome not in transition:
            continue
        target = transition[outcome]
        if target == "Done":
            return None, "Done belongs to the tracker and pr-gate, not an agent.", True
        if target == "previous status":
            return None, "Only a human moves a ticket out of Blocked.", True
        return target, "", False
    return None, f"No transition from {current!r} with outcome {outcome!r}. Set Blocked.", False


def tokens(text):
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS}


def similarity(a, b):
    """Jaccard similarity of two word sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_issues(node):
    """Return the first issues list in a saved Atlassian or REST response, or None."""
    if isinstance(node, dict):
        if "issues" in node:
            issues = node["issues"]
            if isinstance(issues, dict) and isinstance(issues.get("nodes"), list):
                return issues["nodes"]
            if isinstance(issues, list):
                return issues
        for value in node.values():
            found = find_issues(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_issues(value)
            if found is not None:
                return found
    return None
