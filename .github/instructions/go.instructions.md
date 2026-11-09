---
applyTo: "**/*.go"
description: "Use when: writing or reviewing Go code in this repository."
---

- Format with `gofmt`. Run `go vet ./...` before opening a pull request.
- Return errors. Wrap them with context: `fmt.Errorf("upload video: %w", err)`.
- Accept `context.Context` as the first argument in functions that do I/O.
- Keep HTTP handlers thin. Put business logic in its own package.
- Read config from environment variables. Never hard-code credentials.
- Use table-driven tests with `t.Run` for each case.
