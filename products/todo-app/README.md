# Todo app

Foundation for the Todo app (SCRUM-7, PR-1). It has three parts in one npm workspace:

- `apps/web`: Next.js (App Router), TypeScript and Tailwind CSS. Root page only, port 3000.
- `apps/api`: Express and TypeScript. `GET /health`, and Prisma client wiring. Port 4000 by default.
- `prisma/` and `prisma.config.ts`: Prisma 7 with PostgreSQL. The schema has no models in PR-1.

Run every command from `products/todo-app/`. Install once with `npm ci`.

## Requirements

- Node.js `^20.19.0 || ^22.12.0 || >=24.0.0`. This is the range Prisma 7 supports. The engines field in `package.json` enforces it.
- npm 10 or later.

## Build

```sh
npm run build -w apps/web      # Next.js build, writes apps/web/.next/
npm run build -w apps/api      # generates the Prisma client, then compiles to apps/api/dist/
```

## Run locally

```sh
npm run start -w apps/web      # web on http://localhost:3000 (run npm run build -w apps/web first)
cp .env.example .env           # then replace the placeholders in .env with your values
node --env-file=.env apps/api/dist/index.js   # API on port 4000
```

The API needs `DATABASE_URL` at startup, even though `/health` does not use it.

## Health endpoint

```sh
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4000/health   # 200
curl -s http://localhost:4000/health                                   # {"status":"ok"}
```

`/health` does not check the database. A readiness check is a later story.

## Configuration

| Name           | Required           | Meaning                                                                               |
| -------------- | ------------------ | ------------------------------------------------------------------------------------- |
| `DATABASE_URL` | Yes, for API start | PostgreSQL connection URL, `postgresql://...`. No default. The value is never logged. |
| `PORT`         | No                 | API port, 1 to 65535. Defaults to `4000`.                                             |

If `DATABASE_URL` is unset, the API exits with code 1 and prints a message that names `DATABASE_URL`. It never prints a value. Values come from the environment or from a local `.env`, which is gitignored. `.env.example` lists the names with placeholders only.

## Checks

```sh
npm run typecheck    # tsc --noEmit for web and api (api generates the Prisma client first)
npm run lint         # eslint . then prettier --check .
npm run build        # next build and the API compile
npm test             # API unit tests (health, config, Prisma wiring)
npm run db:check     # prisma validate, then prisma generate. No database needed.
npm run verify       # typecheck, lint, build, test and db:check, in that order
npm run secrets:scan # secret scan over tracked files (see Secrets)
```

## Styling

Tailwind CSS v4 is wired in `apps/web/next.config.ts` through `@tailwindcss/turbopack`. Styles are in `apps/web/app/globals.css`. Utility classes in `apps/web/app` are compiled into `apps/web/.next/static/css` at build time.

## Database

- The datasource URL is read from `DATABASE_URL` in `prisma.config.ts`. The schema sets only `provider = "postgresql"`.
- `npm run db:check` runs `prisma validate` and `prisma generate`. The wrapper `scripts/prisma-offline.mjs` gives the child process a placeholder URL with no credentials. Prisma 7 needs a value to load its config, and neither command connects to a database. A real `DATABASE_URL` is never used by `db:check`.
- The generated client goes to `apps/api/src/generated/prisma`. It is gitignored and rebuilt by `generate`.
- `migrations/` holds the migration history. It is empty in PR-1. The first migration (`Todo`) comes in PR-2.

## Migration policy

- No script, workflow or agent applies a migration.
- `npm run db:migrate:status` runs `prisma migrate status`. It is read-only, and it needs a throwaway local PostgreSQL.
- `npm run db:migrate:deploy` runs `prisma migrate deploy`. **Humans only.** Never run it against a shared or production database without approval.
- `prisma migrate dev`, `prisma migrate reset` and `prisma db push` are not scripts. Do not run them against a shared database.

## Secrets

- Only `.env.example` is tracked. Real env files are gitignored.
- `npm run secrets:scan` checks that no env file is tracked and runs `git grep` over the tracked files. Patterns are in `scripts/secret-patterns.txt`. The scan prints file and line numbers only. A finding means the credential is leaked. Rotate it first.
- Do not put credentials in code, config or test fixtures. Test URLs carry no credentials.
