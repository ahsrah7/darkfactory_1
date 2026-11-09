---
name: tracker-state-machine
description: "Use when: moving a tracker ticket between states, deciding the next status, handling Blocked tickets, or writing transition comments in the dark factory."
---

# Tracker state machine

The source of truth is [state-machine.json](../../factory/state-machine.json).

## Procedure

1. Read the ticket's current status.
2. Find the transition where `from` equals that status. If none exists, set Blocked and stop.
3. Do the agent's work. Use the `onSuccess`, `onApproved`, `onRejected`, `onFail` or `onPass` target based on the outcome.
4. Write a comment: the status you moved from, the status you moved to, and links to evidence (PR, test run, design doc).
5. Move the ticket.

## Rules

- Never skip a state.
- Never move a ticket out of Blocked. Only a human does that.
- Count rework. When a ticket reaches `maxReworkIterations` in [config.json](../../factory/config.json), move it to Blocked.
- Keep comments factual. Link evidence instead of pasting long logs.
