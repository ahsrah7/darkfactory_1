---
name: acceptance-criteria
description: "Use when: writing or reviewing acceptance criteria for a user story, or checking that criteria are testable."
---

# Acceptance criteria

Write each criterion in Given / When / Then form. One behavior per criterion.

```
Given a signed-in user with a video in their library
When they open the playlist
Then the playlist plays the first video
```

## Cover

- Happy path: the main behavior works.
- Errors: invalid input, network failure, not found.
- Permissions: a user without access is refused.
- Empty state: no data yet.

## Checks

- Each criterion can be turned into one automated test.
- No criterion depends on a design choice. Put that in the design doc.
- Numbers and limits are explicit. Example: "file size up to 2 GB".
- If a criterion needs a product decision, ask a question instead of guessing.
