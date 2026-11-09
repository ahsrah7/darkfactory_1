---
name: jira-api
description: "Use when: a factory skill script must call the Jira REST API, or when changing how the factory authenticates to Jira. Covers the shared client, env-var credentials and the endpoints in use."
---

# Jira API client

The shared client is [jira_api.py](scripts/jira_api.py). Every Jira skill script imports it. The scripts call Jira with Basic auth from the runner's environment variables. Run them from the repo root with `execute`.

## Configuration

These are the same variable names used by [check-jira-statuses.cjs](../../factory/scripts/check-jira-statuses.cjs) and [dispatch.cjs](../../factory/scripts/dispatch.cjs):

- `JIRA_BASE_URL`: the site URL. It must use https. http is allowed only for localhost, for tests.
- `JIRA_EMAIL` and `JIRA_API_TOKEN`: Basic auth.
- `JIRA_PROJECT_KEY`: the default project.

Agents run the scripts with these variables already set by the runner. The scripts read them directly. Agents must not print, copy or post their values to Jira, into chat, or into tickets and comments. Every Jira write goes through `check_no_credentials`, which refuses text that looks like a credential before anything is sent. A missing variable is reported by name only.

## Endpoints

| Operation | Method and path | Used by |
|---|---|---|
| Search (follows nextPageToken) | POST `/rest/api/3/search/jql` | search_issues, find_duplicates, create_issue |
| Read one issue | GET `/rest/api/3/issue/{key}` | read_issue, apply_transition |
| List comments | GET `/rest/api/2/issue/{key}/comment` | read_issue `--comments` |
| Project statuses | GET `/rest/api/3/project/{key}/statuses` | check_statuses |
| List transitions | GET `/rest/api/3/issue/{key}/transitions` | apply_transition |
| Transition | POST `/rest/api/3/issue/{key}/transitions` | apply_transition |
| Add comment | POST `/rest/api/2/issue/{key}/comment` | build_comment `--issue` |
| Replace comment | PUT `/rest/api/2/issue/{key}/comment/{id}` | build_comment `--comment-id` |
| Create issue | POST `/rest/api/2/issue` | create_issue |

## Rules

- Errors print the HTTP status and the first 500 characters of Jira's reply. Credentials never appear in an error message.
- Writes go only through the scripts named in each skill, and only after the state machine allows the move.
- Tests point `JIRA_BASE_URL` at a local mock. Never run a write against the real project in a test.
