---
name: pr-review-checklist
description: "Use when: reviewing a pull request for logic, security, style, or test coverage in the dark factory."
---

# PR review checklist

Work through each section. Report only findings you can point to by file and line.

## Logic
- The change matches the story's acceptance criteria.
- Edge cases and error paths are handled.
- No dead code or unused parameters.

## Security
- No secrets, tokens, or credentials in code, config, or tests.
- Inputs are validated at the boundary.
- Authorization is checked on every new endpoint.
- No SQL built from string concatenation.
- Logs do not contain personal data or tokens.

## Tests
- Each acceptance criterion has at least one test.
- Tests assert real outcomes.
- Tests run locally with documented steps.

## Style
- Follows the instruction files in `.github/instructions`.
- Names are clear. Functions are small.
- Public functions have one-line comments only where the code cannot explain itself.

## Output
Each finding: file and line, the rule it breaks, and the smallest fix.
