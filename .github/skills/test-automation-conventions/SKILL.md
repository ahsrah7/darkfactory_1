---
name: test-automation-conventions
description: "Use when: automating a test case, creating a test folder, writing a test README, or running automated tests in the dark factory."
---

# Test automation conventions

## Layout

Each test case gets its own folder under `tests/`:

```
tests/<tracker-key>/
  README.md        dependencies, environment variables, run command, linked tickets
  <test files>
```

## Rules

- Test names state the behavior: `rejects_upload_over_size_limit`, not `test_3`.
- Config comes from environment variables. Never hard-code credentials or hosts.
- Tests are deterministic. Use fixed clocks and seeded data. No sleeps.
- Each test cleans up the data it creates.
- Tests do not depend on each other's order.
- A test that fails must fail for the reason in its bug. A test that passes must check a real outcome.

## Run

The README must include one command that runs the test alone, and one that runs the full suite.
