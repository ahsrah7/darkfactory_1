---
name: bug-triage
description: "Use when: filing a bug, checking for duplicate bugs, linking a failing test to a bug, or finding the root cause of a repeated failure in the dark factory."
---

# Bug triage

## Before filing

1. Search open bugs for the same component and the same observed behavior.
2. If a match exists, link the failing test to it. Do not create a duplicate.
3. If a previous bug for the same test was closed and the test failed again, file a new bug. Link the old one and note that the earlier fix did not hold.

## Filing

Include:
- Observed behavior, with screenshots or logs attached.
- Expected behavior, taken from the acceptance criteria.
- Steps to reproduce.
- Root cause, or the best known hypothesis, labeled as a hypothesis.
- Links: failing test, story, previous bugs.

## Linking

- Failing test is blocked by bug.
- One bug can block many tests. One test can be blocked by many bugs.
- When the bug is fixed, rerun every linked test. Do not close tests by hand.
